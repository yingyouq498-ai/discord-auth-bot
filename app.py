import os
import requests
import psycopg2
from flask import Flask, request, abort

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-this")

# Discord設定
CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI")
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))
ROLE_ID = int(os.getenv("DISCORD_ROLE_ID"))

# データベース
DATABASE_URL = os.getenv("DATABASE_URL")

# 簡易ログ閲覧用パスワード
LOGS_PASSWORD = os.getenv("LOGS_PASSWORD", "secretpassword")

# 本物のIPを取得
def get_real_ip(req):
    if "X-Forwarded-For" in req.headers:
        return req.headers["X-Forwarded-For"].split(",")[0].strip()
    return req.remote_addr

# 初回起動時にテーブル作成
def init_db():
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS auth_logs (
                id SERIAL PRIMARY KEY,
                discord_id TEXT NOT NULL,
                email TEXT,
                ip TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("✅ auth_logs テーブル準備完了")
    except Exception as e:
        print(f"❌ DB初期化失敗: {e}")

# Flask起動時に必ずテーブル作成
init_db()

# 認証ページ
@app.route("/")
def index():
    auth_url = (
        "https://discord.com/api/oauth2/authorize"
        f"?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
        "&response_type=code&scope=identify%20email%20guilds.join"
    )
    return f'<a href="{auth_url}">Discordで認証する</a>'

# コールバック（Discord認証処理）
@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "Error: no code", 400

    # アクセストークン取得
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "scope": "identify email guilds.join",
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    r = requests.post("https://discord.com/api/oauth2/token", data=data, headers=headers)
    r.raise_for_status()
    tokens = r.json()
    access_token = tokens["access_token"]

    # ユーザー情報取得
    user = requests.get(
        "https://discord.com/api/users/@me",
        headers={"Authorization": f"Bearer {access_token}"}
    ).json()

    discord_id = user["id"]
    email = user.get("email")
    ip = get_real_ip(request)

    # DBに保存
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO auth_logs (discord_id, email, ip) VALUES (%s, %s, %s)",
            (discord_id, email, ip)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        return f"❌ DB保存失敗: {e}", 500

    # ロール付与
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    url = f"https://discord.com/api/guilds/{GUILD_ID}/members/{discord_id}/roles/{ROLE_ID}"
    r = requests.put(url, headers=headers)

    if r.status_code in (200, 204):
        return f"✅ 認証成功！ メール: {email} / IP: {ip} （保存済み）"
    else:
        return f"❌ ロール付与失敗: {r.text}", 500

# 保存データの閲覧ページ
@app.route("/logs")
def logs():
    # 簡易認証
    pw = request.args.get("pw")
    if pw != LOGS_PASSWORD:
        abort(403)  # 認証失敗

    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        cur = conn.cursor()
        cur.execute("SELECT discord_id, email, ip, created_at FROM auth_logs ORDER BY created_at DESC")
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        return f"❌ DB取得失敗: {e}", 500

    # HTMLテーブルで表示
    html = "<h2>認証ログ</h2><table border='1'><tr><th>Discord ID</th><th>Email</th><th>IP</th><th>日時</th></tr>"
    for row in rows:
        html += f"<tr><td>{row[0]}</td><td>{row[1]}</td><td>{row[2]}</td><td>{row[3]}</td></tr>"
    html += "</table>"
    return html

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
