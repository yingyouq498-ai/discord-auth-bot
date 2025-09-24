import os
import psycopg2
import requests
from flask import Flask, request, redirect

app = Flask(__name__)

# ==============================
# 環境変数（Render の Dashboard に設定）
# ==============================
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "https://YOUR-APP.onrender.com/callback")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID")
DISCORD_ROLE_ID = os.getenv("DISCORD_ROLE_ID")
DATABASE_URL = os.getenv("DATABASE_URL")
LOGS_PASSWORD = os.getenv("LOGS_PASSWORD", "changeme")

# ==============================
# DB 初期化
# ==============================
def init_db():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS auth_logs (
            id SERIAL PRIMARY KEY,
            discord_id TEXT,
            email TEXT,
            ip TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_blacklisted BOOLEAN DEFAULT FALSE
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

init_db()

# ==============================
# 認証スタート
# ==============================
@app.route("/start")
def start():
    url = (
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={DISCORD_CLIENT_ID}"
        f"&redirect_uri={DISCORD_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=identify%20email%20guilds.join"
    )
    return f"""
    <h1>Discord 認証ページ</h1>
    <p>下のボタンを押して認証を完了してください。</p>
    <a href="{url}"><button>Discordでログイン</button></a>
    <p>このサービスを利用することで、<a href="/terms">利用規約</a>に同意したものとみなされます。</p>
    """

# ==============================
# Discord OAuth2 Callback
# ==============================
@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "❌ 認証エラー: code がありません"

    # アクセストークン取得
    data = {
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": DISCORD_REDIRECT_URI,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    r = requests.post("https://discord.com/api/oauth2/token", data=data, headers=headers)
    if r.status_code != 200:
        return f"❌ トークン取得失敗: {r.text}"
    access_token = r.json().get("access_token")

    # ユーザー情報取得
    user = requests.get(
        "https://discord.com/api/users/@me",
        headers={"Authorization": f"Bearer {access_token}"}
    ).json()
    discord_id = user.get("id")
    email = user.get("email")

    # IP取得
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)

    # DB保存（荒らしIPは is_blacklisted=True）
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO auth_logs (discord_id, email, ip, is_blacklisted) VALUES (%s, %s, %s, %s)",
        (discord_id, email, ip, False)
    )
    conn.commit()
    cur.close()
    conn.close()

    # ロール付与
    url = f"https://discord.com/api/guilds/{DISCORD_GUILD_ID}/members/{discord_id}/roles/{DISCORD_ROLE_ID}"
    headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
    role_res = requests.put(url, headers=headers)

    if role_res.status_code == 204:
        return f"✅ 認証成功！ メール: {email} / IP: {ip} （保存済み）"
    else:
        return f"❌ ロール付与失敗: {role_res.text}"

# ==============================
# ログ閲覧
# ==============================
@app.route("/view_logs")
def view_logs():
    password = request.args.get("pw")
    if password != LOGS_PASSWORD:
        return "❌ アクセス拒否: パスワードが違います"

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT discord_id, email, ip, created_at, is_blacklisted FROM auth_logs ORDER BY created_at DESC LIMIT 50")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    html = "<h1>認証ログ一覧</h1><table border='1'><tr><th>Discord ID</th><th>Email</th><th>IP</th><th>日時</th><th>ブラックリスト</th></tr>"
    for r in rows:
        html += f"<tr><td>{r[0]}</td><td>{r[1]}</td><td>{r[2]}</td><td>{r[3]}</td><td>{r[4]}</td></tr>"
    html += "</table>"
    return html

# ==============================
# 利用規約
# ==============================
@app.route("/terms")
def terms():
    return """
    <h1>利用規約</h1>
    <p>本サービスを利用することで、以下の規約に同意したものとみなされます。</p>
    <h2>第2条（取得する情報）</h2>
    <ul>
      <li>Discord アカウントに紐づくユーザーID</li>
      <li>Discord に登録されているメールアドレス</li>
      <li>アクセス時のIPアドレス</li>
      <li>認証日時</li>
    </ul>
    <h2>第3条（利用目的）</h2>
    <ul>
      <li>認証済みユーザーへの自動ロール付与</li>
      <li>荒らし防止・不正利用対策</li>
    </ul>
    <h2>第4条（保存期間）</h2>
    <ul>
      <li>通常ユーザーの情報は1週間で自動削除</li>
      <li>荒らし・迷惑行為ユーザーは無期限保存</li>
    </ul>
    <h2>第5条（禁止事項）</h2>
    <ul>
      <li>複数アカウントの不正利用</li>
      <li>VPNや匿名回線の利用</li>
      <li>サービスの妨害</li>
    </ul>
    <p>詳細版は運営までお問い合わせください。</p>
    <p><a href="/start">認証ページに戻る</a></p>
    """

# ==============================
# メイン
# ==============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))    

@app.errorhandler(Exception)
def handle_exception(e):
    import traceback
    return f"<pre>Internal Server Error\n{traceback.format_exc()}</pre>", 500
