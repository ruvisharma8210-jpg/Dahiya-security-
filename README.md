# 🛡️ Telegram Group Guard Bot

Inline-button control panel wala Telegram moderation bot (Python, python-telegram-bot v21, SQLite).

## ✅ Features
**1. ⚙️ Auto-Accept & Welcome** (`/welcome`)
- Auto-Accept join requests: 🟢 ON / 🔴 OFF (live toggle)
- ✏️ Edit Welcome Text — chat me hi naya message set karein (`Welcome {name}, your ID is {id}`)
- 👁️ Preview, ♻️ Reset

**2. 🛡️ Security & Moderation** (`/secpanel`)
- **Anti-Link:** Active/Inactive · Action: Delete Only / Warn / Mute (10m/1h/24h) / Permanent Ban · Trusted domains add/remove
- **Bad Words:** ➕ Add Word · 🗑️ Remove Word · 📋 View List (admin ke DM me) · Warning limit · Limit ke baad Mute / Ban / Perm Ban
- **Anti-Flood:** X second me Y se zyada messages = spam · Mute 5m/30m/1h ya Direct Ban
- **Anti-Left / Anti-Raid:** Join karke jaldi left karne wale ko auto-ban (30s/60s/5m)
- **Lockdown:** 1 click me poora group lock/unlock

**3. ⏳ Punishment Durations** (`/punish`)
- Mute: 10m / 1h / 24h / Permanent / Custom (`15m`, `2h`, `3d`, `1w`)
- Ban: 1 Day / 7 Days / Permanent
- Warning limit: 3 / 5 / Custom (1–20)

**4. 📂 Telethon Sessions Manager** (`/sessions` — sirf owner, bot ke private chat me)
- ➕ Add New Session — session string paste karein; message turant delete, string **encrypted** save
- 🔄 Refresh / Check Status — har session 🟢 alive / 🔴 dead / ⛔ banned
- ❌ Revoke / Delete — 🚪 Revoke = Telegram se logout, 🗑 Delete only = sirf list se hatao
- `gen_session.py` — apne computer par chalakar session string banaiye

Other commands: `/panel` (sab kuch ek jagah), `/lockdown`, `/unlock`, `/warn` `/unwarn` `/warns` (message ko reply karke), `/cancel`.

## 🚀 Setup (5 minute)
1. @BotFather se bot banaiye, token copy karein.
2. **Zaroori:** BotFather → `/setprivacy` → apna bot → **Disable** (taaki bot group ke saare messages padh sake).
3. Python 3.10+ install hona chahiye. Phir:
   ```bash
   pip install -r requirements.txt
   cp .env.example .env      # .env me BOT_TOKEN daaliye
   python run.py
   ```
4. Bot ko group me add karke **Admin** banaiye — rights: *Delete messages, Ban users, Invite users via link*.
5. Group me `/panel` likhiye. 🎉

### 📂 Session Manager setup
1. https://my.telegram.org → *API development tools* se `API_ID` aur `API_HASH` lekar `.env` me daaliye.
2. `.env` me `OWNER_IDS` me apni Telegram user ID daaliye (@userinfobot se milegi).
3. Computer par `python gen_session.py` chalayein → phone, code (aur 2FA password) daalein → string copy karein.
4. Bot ke private chat me `/sessions` → ➕ Add New Session → string paste.

> ⚠️ Session string = poore account ki chaabi. Kisi ko na dein. `secret.key` (ya `SESSION_SECRET`) ka backup rakhein — iske bina saved sessions decrypt nahi honge.

> Auto-Accept ke liye group ka invite link "Request admin approval" wala hona chahiye.
> Welcome aur Anti-Left ke liye bot ka admin hona zaroori hai (tabhi Telegram join/leave updates bhejta hai).

## 🖥️ 24/7 chalane ke liye (VPS)
```bash
nohup python run.py > bot.log 2>&1 &
```
ya `systemd` / `pm2 start run.py --interpreter python3` use karein.

## ☁️ Render FREE (Web Service)
Bot me chhota built-in web server hai (Flask nahi chahiye) — Render jo `PORT` deta hai us par `OK` dikhata hai.
1. New + → **Web Service** → ye repo → Free plan
2. Build: `pip install -r requirements.txt` · Start: `python run.py`
3. Environment variables daaliye (BOT_TOKEN, OWNER_IDS, API_ID, API_HASH, SESSION_SECRET)
4. Free service 15 min baad so jaati hai — https://uptimerobot.com par apna `https://<app>.onrender.com` URL har 5 min ping karwaiye.
> Free plan me disk nahi hoti: redeploy/restart par settings aur sessions reset ho sakte hain.

## 📁 Files
```
run.py              # start
bot/main.py         # handlers register
bot/handlers.py     # commands, buttons, moderation, welcome
bot/panels.py       # saare button panels
bot/db.py           # SQLite storage
bot/utils.py        # mute/ban/duration helpers
bot/sessions.py     # Telethon Sessions Manager
gen_session.py      # session string generator (local)
```


## 🔑 Session String Generator (sab users ke liye)
Bot ke private chat me `/start` → **🔑 Session String Generator** (ya `/session`).
Library chuniye: **Telethon, mtcute, Kurigram, GramJS, GoTG** → API ID/HASH → phone → code (spaces ke saath, jaise `1 2 3 4 5`) → 2FA password (agar ho).
String sirf us chat me milti hai — bot kuch save nahi karta, environment me kuch daalna nahi padta.

## ⚙️ Buttons se settings
- `/start` (private) → **Group Settings / Welcome Message / Auto-Approve** buttons — group chuniye aur wahin se badliye.
- **👋 Welcome Message**: on/off, text edit, preview, reset, auto-delete (1m/5m/10m), purana welcome hatao.
- **✅ Auto-Approve**: on/off, delay (instant/10s/30s/1m), approve hone par DM + DM text, approved count.
- `/id` — apni Telegram ID dekhein (OWNER_IDS ke liye).
