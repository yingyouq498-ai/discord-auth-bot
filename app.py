import os
import requests
import psycopg2
from flask import Flask, request, abort, redirect
from datetime import datetime, timedelta
import ipaddress

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-this")

# --- 必須環境変数（Renderの環境変数に設定してください） ---
CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
# Discordに登録した Redirect URI と完全一致させてください
REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "https://discord-auth-bot-ngw0.onrender.com/callback")
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID") or 0)
ROLE_ID = int(os.getenv("DISCORD_ROLE_ID") or 0)

DATABASE_URL = os.getenv("DATABASE_URL")
LOGS_PASSWORD = os.getenv("LOGS_PASSWORD", "secretpassword")
ADMIN_PW = os.getenv("ADMIN_PW", "adminpassword")  # ブラックリスト用管理パスワード

# --- DB初期化（is_blacklisted を追加） ---
def init_db():
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS auth_logs (
            id SERIAL PRIMARY KEY,
            discord_id TEXT NOT NULL,
            email TEXT,
            ip TEXT,
            agreed_terms BOOLEAN DEFAULT TRUE,
            is_blacklisted BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    cur.close()
    conn.close()
    print("DB initialized")

init_db()

# --- ユーティリティ ---
def get_real_ip(req):
    if "X-Forwarded-For" in req.headers:
        return req.headers["X-Forwarded-For"].split(",")[0].strip()
    return req.remote_addr

# 誤爆ゼロ運用のため、ブロックは「特定IPのみ」
VPN_IPS = [
    "133.11.0.0/16",      # サンプル: 筑波大系（必要なら追加・更新）
    "133.11.128.0/17"
]
def is_vpn(ip):
    try:
        ip_addr = ipaddress.ip_address(ip)
        for net in VPN_IPS:
            if ip_addr in ipaddress.ip_network(net):
                return True
    except Exception:
        return False
    return False

# 自動削除：通常ユーザー（is_blacklisted=FALSE）で7日より古いものを削除
def cleanup_old_logs():
    try:
        cutoff = datetime.utcnow() - timedelta(days=7)
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        cur = conn.cursor()
        cur.execute("DELETE FROM auth_logs WHERE created_at < %s AND is_blacklisted = FALSE", (cutoff,))
        deleted = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        print(f"cleanup_old_logs: deleted {deleted} rows older than {cutoff.isoformat()}")
    except Exception as e:
        print("cleanup_old_logs error:", e)

# 呼び出しタイミング：起動時の一回クリーンアップ
cleanup_old_logs()

# --- ルート ---
@app.route("/terms")
def terms():
    # 利用規約はここに好きに書き換えてOK
    html = """
    <h1>利用規約（簡易）</h1>
    <ol>
      <li>取得情報: Discord ID, メールアドレス, アクセスIP</li>
      <li>保存: 通常は取得後1週間で自動削除。荒らしは永久保存。</li>
      <li>複数アカウント作成や特定VPNの利用は禁止です。</li>
      <li>認証成功者のみ指定のロールを付与します。</li>
      <li>管理者はログを確認・ブラックリスト化できます。</li>
    </ol>
    <p><a href="/start">同意して認証に進む</a></p>
    """
    return html

@app.route("/start")
def start():
    # 利用規約を表示してから来る想定だが、ここでも単独アクセスを許可
    # OAuth の URL を生成しつつ、JS不要のシンプルリダイレクト用リンクを返す
    auth_url = (
        "https://discord.com/api/oauth2/authorize"
        f"?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
        "&response_type=code&scope=identify%20email%20guilds.join"
    )
    html = f"""
    <h1>同意済みユーザー向け</h1>
    <p>下のボタンで Discord の認証ページに移動します。</p>
    <p><a href="{auth_url}"><button>Discordで認証する</button></a></p>
    <p>注意: Botをサーバーに招待（Manage Roles 権限など）していないとロール付与に失敗します。Bot招待URLは Developer Portal で生成してください。</p>
    """
    return html

@app.route("/callback")
def callback():
    # コールバック直前に古いログを削除（継続的クリーンアップ）
    cleanup_old_logs()

    code = request.args.get("code")
    if not code:
        return "Error: no code", 400

    # トークン取得
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "scope": "identify email guilds.join",
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    try:
        r = requests.post("https://discord.com/api/oauth2/token", data=data, headers=headers)
        r.raise_for_status()
    except Exception as e:
        return f"Discord token request failed: {e}", 500

    tokens = r.json()
    access_token = tokens.get("access_token")
    if not access_token:
        return "Failed to get access token", 500

    # ユーザー情報取得
    try:
        user = requests.get("https://discord.com/api/users/@me", headers={"Authorization": f"Bearer {access_token}"}).json()
    except Exception as e:
        return f"Discord user fetch failed: {e}", 500

    discord_id = user.get("id")
    email = user.get("email")
    ip = get_real_ip(request)

    # VPNチェック（誤爆ゼロ運用：特定IPのみブロック）
    if is_vpn(ip):
        return "⚠ このIP範囲（特定VPN）は利用できません。ロール付与は行われません。"

    # DB接続
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    cur = conn.cursor()

    # 複垢チェック（同IPの既存ログがあれば複垢扱い）
    cur.execute("SELECT COUNT(*) FROM auth_logs WHERE ip=%s", (ip,))
    count = cur.fetchone()[0]
    if count > 0:
        cur.close()
        conn.close()
        return "⚠ 同一IPで既に認証が行われています。複垢扱いのためロール付与は行いません。管理者に相談してください。"

    # DB保存（通常ユーザー）: agreed_terms=True, is_blacklisted defaults FALSE
    cur.execute(
        "INSERT INTO auth_logs (discord_id, email, ip, agreed_terms) VALUES (%s,%s,%s,%s)",
        (discord_id, email, ip, True)
    )
    conn.commit()
    cur.close()
    conn.close()

    # ロール付与（Bot権限・ロール階層に注意）
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    url = f"https://discord.com/api/guilds/{GUILD_ID}/members/{discord_id}/roles/{ROLE_ID}"
    r2 = requests.put(url, headers=headers)
    if r2.status_code in (200, 204):
        return f"✅ 認証成功。メール: {email} / IP: {ip}（保存済み）"
    else:
        return f"❌ ロール付与に失敗しました: {r2.status_code} {r2.text}", 500

@app.route("/logs")
def logs():
    # logs表示前にクリーンアップ
    cleanup_old_logs()

    pw = request.args.get("pw")
    if pw != LOGS_PASSWORD:
        abort(403)

    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    cur = conn.cursor()
    cur.execute("SELECT discord_id,email,ip,agreed_terms,is_blacklisted,created_at FROM auth_logs ORDER BY created_at DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    html = "<h2>認証ログ</h2><table border='1'><tr><th>Discord ID</th><th>Email</th><th>IP</th><th>同意</th><th>ブラックリスト</th><th>日時</th></tr>"
    for row in rows:
        html += f"<tr><td>{row[0]}</td><td>{row[1]}</td><td>{row[2]}</td><td>{row[3]}</td><td>{row[4]}</td><td>{row[5]}</td></tr>"
    html += "</table>"
    return html

# 管理者用: ブラックリスト登録（永久保存）
# 使い方: /admin/blacklist?pw=管理パスワード&discord_id=対象のDiscordID
@app.route("/admin/blacklist")
def admin_blacklist():
    pw = request.args.get("pw")
    if pw != ADMIN_PW:
        abort(403)
    target = request.args.get("discord_id")
    if not target:
        return "discord_id required", 400
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    cur = conn.cursor()
    cur.execute("UPDATE auth_logs SET is_blacklisted = TRUE WHERE discord_id = %s", (target,))
    updated = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    return f"Updated {updated} rows (set is_blacklisted=TRUE) for discord_id={target}"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
