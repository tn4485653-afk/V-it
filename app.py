from flask import Flask, jsonify, request
import aiohttp
import asyncio
import json
import threading
import time
import requests
from byte import encrypt_api, Encrypt_ID
from visit_count_pb2 import Info

app = Flask(__name__)

# ---------------- CONFIG ----------------

ACCOUNT_FILE = "account.json"
TOKEN_API_URL = "http://jwt.thug4ff.xyz/token"
REFRESH_INTERVAL = 5 * 60 * 60

TOKEN_FILE = "token_vn.json"
TOKENS_PER_REQUEST = 20
TARGET_VISIT = 5000   # 🎯 tổng visit

token_rotation = {}

# ---------------- TOKEN REFRESH ----------------

def load_accounts():
    try:
        with open(ACCOUNT_FILE) as f:
            return json.load(f)
    except:
        return []

def fetch_token(uid, password):
    try:
        r = requests.get(f"{TOKEN_API_URL}?uid={uid}&password={password}", timeout=20)
        data = r.json()
        return data.get("token")
    except:
        return None

def refresh_tokens():
    print("🔄 Refreshing tokens...")

    accounts = load_accounts()
    new_tokens = []

    for acc in accounts:
        uid = acc.get("id")
        password = acc.get("pass")

        token = fetch_token(uid, password)

        if token:
            new_tokens.append({"token": token})

    if new_tokens:
        with open(TOKEN_FILE,"w") as f:
            json.dump(new_tokens,f,indent=4)

        print("✅ Saved tokens:",len(new_tokens))

def refresh_loop():
    while True:
        refresh_tokens()
        print("⏰ Sleep 5 hours")
        time.sleep(REFRESH_INTERVAL)

# ---------------- TOKEN LOAD ----------------

def load_tokens():
    try:
        with open(TOKEN_FILE) as f:
            data = json.load(f)

        return [i["token"] for i in data if "token" in i]
    except:
        return []

def get_tokens(server):

    global token_rotation

    if server not in token_rotation:

        tokens = load_tokens()

        token_rotation[server] = {
            "tokens": tokens,
            "index": 0
        }

    data = token_rotation[server]

    tokens = data["tokens"]
    idx = data["index"]

    if not tokens:
        return []

    end = (idx + TOKENS_PER_REQUEST) % len(tokens)

    if idx < end:
        batch = tokens[idx:end]
    else:
        batch = tokens[idx:] + tokens[:end]

    token_rotation[server]["index"] = end

    return batch

# ---------------- API ----------------

def get_url(server):
    if server == "IND":
        return "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
    elif server in {"BR","US","SAC","NA"}:
        return "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
    else:
        return "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow"

def parse_proto(data):

    try:
        info = Info()
        info.ParseFromString(data)

        return {
            "uid": info.AccountInfo.UID,
            "nickname": info.AccountInfo.PlayerNickname,
            "likes": info.AccountInfo.Likes,
            "level": info.AccountInfo.Levels
        }

    except:
        return None

async def visit(session,url,token,payload):

    headers = {
        "Authorization": f"Bearer {token}",
        "ReleaseVersion": "OB52",
        "X-GA": "v1 1"
    }

    try:
        async with session.post(url,headers=headers,data=payload,ssl=False) as r:

            if r.status == 200:
                return True,await r.read()

    except:
        pass

    return False,None

async def run_visit(tokens,uid,server):

    url = get_url(server)

    connector = aiohttp.TCPConnector(limit=0)

    encrypted = encrypt_api("08"+Encrypt_ID(str(uid))+"1801")
    payload = bytes.fromhex(encrypted)

    success = 0
    player = None

    async with aiohttp.ClientSession(connector=connector) as session:

        while success < TARGET_VISIT:

            batch = min(TARGET_VISIT-success,TOKENS_PER_REQUEST)

            tasks = [
                asyncio.create_task(
                    visit(session,url,tokens[i%len(tokens)],payload)
                )
                for i in range(batch)
            ]

            results = await asyncio.gather(*tasks)

            for ok,data in results:

                if ok:
                    success += 1

                    if not player and data:
                        player = parse_proto(data)

            print("Success:",success)

    return success,player

# ---------------- ROUTE ----------------

@app.route("/visit")

def api():

    uid = request.args.get("uid")
    region = request.args.get("region","VN").upper()

    if not uid:
        return jsonify({"error":"uid required"})

    tokens = get_tokens(region)

    if not tokens:
        return jsonify({"error":"no tokens"})

    success,player = asyncio.run(
        run_visit(tokens,int(uid),region)
    )

    return jsonify({
        "uid": uid,
        "region": region,
        "visits_sent": success,
        "target": TARGET_VISIT,
        "tokens_used": len(tokens),
        "message": f"Đã gửi {success} visit cho UID {uid}"
    })

# ---------------- START ----------------

if __name__ == "__main__":

    thread = threading.Thread(target=refresh_loop,daemon=True)
    thread.start()

    print("🚀 Visit API Running")
    print("🌐 http://0.0.0.0:5070/visit?region=vn&uid=")

    app.run(host="0.0.0.0",port=5070)