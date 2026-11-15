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
bot/sessgen.py      # public session string generator
bot/sessrevoke.py   # public session string revoke
bot/sessfmt.py      # string formats (build + parse)
bot/hub.py          # Dahiya Hub: String permission + activity report
bot/owner.py        # 🎛️ Owner Control Center (/panel)
bot/cloner.py       # 🤖 /clone — one-click clones
bot/guard.py        # 👮 admin check + 📵 anti-screenshot
bot/store.py        # whitelist, clones, logs storage
bot/wiring.py       # handlers (master + clones)
gen_session.py      # session string generator (local)
```


## 🆕 v3 — A to Z Owner Features

**1. 👮 Group Admin Validation** — bot group me tabhi kaam karta hai jab wo **Admin** ho.
Admin nahi hai to command/button par turant warning: *"इस ग्रुप में काम करने के लिए कृपया मुझे पहले Admin बनाइए!"*
(Add hote hi bhi yahi message aata hai.)

**2. 📵 Anti-Screenshot & Screen-Recording Lock** — `/panel` → 🛡️ Security & Privacy → master toggle.
ON karte hi bot ke saare groups me Telegram ka *Restrict Saving Content* lagta hai (screenshot, screen recording,
forward, save — sab band). Naye groups me apne aap lagta hai. Telegram Bot API me ye method nahi hai, isliye
bot Telethon se lagata hai: pehle bot account se, phir `/sessions` me saved owner accounts se.
> Zaroori: `.env` me `API_ID` + `API_HASH`. Jo group fail ho (Telegram sirf group Owner ko allow karta hai) wo result me dikhta hai.

**3. 🔑 Restricted Session String** — Generator sirf **OWNER_IDS** aur admin panel ki **whitelist** wale users ke liye
(purana Dahiya Hub permission bhi chalta rahega). Baaki sab ko "Contact admin" + unki ID.

**4. 🤖 Instant One-Click Cloner** — koi bhi user bot ke DM me: `/clone <BotFather_Token>`
→ clone isi server par background me turant LIVE (saare features). Token wala message turant delete hota hai.
Clone ka naam, username, token (encrypted) aur banane wale ki ID record hoti hai. Restart par saare clones apne aap chalu.

**5. 🎛️ Owner Control Center** — bot ke private chat me `/panel` (sirf OWNER_IDS):
- 📊 **Live Dashboard** — total users (24h active), requests pass/fail, join approvals, strings generated, live clones, groups
- 🤖 **Clone Management** — list · token dekho (👁 Show) · ⏹ Stop / ▶️ Start · ✏️ Edit token · 👤 Change owner · 🗑 Delete · ➕ Add
- 🔑 **Session Whitelist** — Telegram ID add (ek saath kai) / tap karke remove
- 🌐 **Connected Groups** — master + clones ke saare groups · members · bot admin hai ya nahi · 🚪 Remote remove (bot leave)
- 🛡️ **Security & Privacy** — Anti-Screenshot master toggle
- 📜 **Activity Logs (A-Z)** — har command, clone, token change, whitelist, moderation, group add/remove; latest se purane tak pages + filters

Naye files: `bot/owner.py` (panel) · `bot/cloner.py` · `bot/guard.py` · `bot/store.py` · `bot/wiring.py` (handlers, master + clones dono)
> Clone tokens `SESSION_SECRET` / `secret.key` se encrypt hote hain — iska backup rakhein. Render free plan par disk nahi hoti,
> isliye restart par clones/logs reset ho sakte hain — paid disk ya VPS behtar hai.

## 🛰️ Dahiya Hub (owner dashboard) — NEW
Bot har jagah (original aur har clone) apne aap **Dahiya Hub** se juda rehta hai (`bot/hub.py`, `HUB_URL`).
- **🔒 Session String button** sirf un logon ke liye chalta hai jinhe admin ne Hub me permission di hai.
  Bot ke `OWNER_IDS` se permission nahi milti — clone banane wala bhi use nahi kar payega.
  Baaki sab ko message milta hai: *Contact to admin for use this button* + unki Telegram ID + 📩 Contact Admin button.
- **Activity**: commands, join-request approve, moderation (warn/mute/ban/flood/link/lockdown),
  group add/remove, string generate (string kabhi nahi bheji jati) — sab Hub dashboard par dikhta hai.
- Hub band ho to String button deny karta hai; baaki bot normal chalta hai.
- Kuch naya `.env` me daalna nahi hai.

## 🔑 Session String Generator (sirf permission wale users)
Bot ke private chat me `/start` → **🔑 Session String Generator 🔒** (ya `/session`).
Library chuniye: **Telethon, mtcute, Kurigram, GramJS, GoTG** → API ID/HASH → phone → code (spaces ke saath, jaise `1 2 3 4 5`) → 2FA password (agar ho).
String sirf us chat me milti hai — bot kuch save nahi karta, environment me kuch daalna nahi padta.

## ⚙️ Buttons se settings
- `/start` (private) → **Group Settings / Welcome Message / Auto-Approve** buttons — group chuniye aur wahin se badliye.
- **👋 Welcome Message**: on/off, text edit, preview, reset, auto-delete (1m/5m/10m), purana welcome hatao.
- **✅ Auto-Approve**: on/off, delay (instant/10s/30s/1m), approve hone par DM + DM text, approved count.
- `/id` — apni Telegram ID dekhein (OWNER_IDS ke liye).

## ♻️ Session String Revoke + Nayi String (sab users ke liye)
Bot ke private chat me `/start` → **♻️ Revoke Session String** (ya `/revoke`).
Purani string paste kijiye (Telethon / mtcute / Kurigram / GramJS / GoTG — library apne aap pehchani jaati hai) → **🗑 Haan, revoke karo**.
Bot Telegram par us string ka logout kar deta hai, string hamesha ke liye band ho jaati hai, aur wahin library buttons aate hain taaki turant **nayi string** le sakein.

## 🩺 Bot jawab nahi de raha? (Render)
1. **Render free service so jaati hai** (15 min koi request nahi) → bot band. Ab bot khud har 10 min apna URL ping karta hai (`RENDER_EXTERNAL_URL` Render apne aap deta hai). Logs me `Keepalive: ...` line dikhni chahiye. Service type **Web Service** hi rakhein.
2. **Logs me `❌ Conflict ... min se chal raha hai`** → isi token se koi doosra bot chal raha hai (doosri Render service, Replit, PC). Use band kijiye, ya BotFather → `/revoke` se naya token lekar sirf Render me `BOT_TOKEN` badliye. Deploy ke turant baad 1–2 conflict normal hain.
3. **`Owner IDs loaded: 0`** → Render → Environment me `OWNER_IDS` = apni Telegram ID (bot me `/id` bhejkar dekhein). Iske bina owner panel / `/sessions` nahi chalega.
4. Free Render ki disk har deploy/restart par saaf hoti hai — `bot.db` (settings, clones) reset ho jaata hai. `SESSION_SECRET` env me zaroor daaliye.
