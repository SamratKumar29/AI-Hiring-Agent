import pandas as pd
import streamlit as st

from brain import config, doctor, health, llm, notify
from ui import common

st.header("Setup & Health")
tabs = st.tabs(["API key", "Models", "Notifications", "Other settings", "Doctor"])


def secret_status(name: str) -> str:
    return "✅ set" if config.get(name) else "❌ not set"


# ------------------------------------------------------------------ API key
with tabs[0]:
    st.write(f"OpenRouter key: {secret_status('OPENROUTER_API_KEY')}  (never displayed)")
    new = st.text_input("Replace the key", type="password", key="new_key", placeholder="sk-or-...")
    a, b = st.columns(2)
    if a.button("Save key", disabled=not new.strip()):
        config.save_env({"OPENROUTER_API_KEY": new.strip()})
        st.success("Saved to brain/.env.")
        st.rerun()
    if b.button("Test key", disabled=common.key_missing()):
        with st.spinner("Contacting OpenRouter..."):
            r = health.check()
        if r["ok"]:
            st.success(f"Works. Model {r['model_used']} answered in {r['latency_s']}s.")
        elif r["key_valid"]:
            st.warning(f"Key is valid but no model answered: {r['error']}")
        else:
            st.error(f"{r['error']}  Check the key at openrouter.ai/keys, or your internet/proxy.")

# ------------------------------------------------------------------ models
def model_editor(title: str, env_name: str, key: str) -> None:
    ss = f"models-{key}"
    if ss not in st.session_state:
        st.session_state[ss] = [m.strip() for m in config.get(env_name).split(",") if m.strip()]
    ms = st.session_state[ss]
    st.markdown(f"**{title}** - tried top to bottom")
    for i, m in enumerate(ms):
        c = st.columns([8, 1, 1, 1])
        c[0].code(m, language=None)
        if c[1].button("↑", key=f"{key}-up-{i}", disabled=i == 0):
            ms[i - 1], ms[i] = ms[i], ms[i - 1]
            st.rerun()
        if c[2].button("↓", key=f"{key}-dn-{i}", disabled=i == len(ms) - 1):
            ms[i + 1], ms[i] = ms[i], ms[i + 1]
            st.rerun()
        if c[3].button("✕", key=f"{key}-rm-{i}"):
            ms.pop(i)
            st.rerun()
    c = st.columns([8, 2])
    new = c[0].text_input("Add model id", key=f"{key}-new", placeholder="vendor/model-name", label_visibility="collapsed")
    if c[1].button("Add", key=f"{key}-add", disabled=not new.strip()):
        if new.strip() not in ms:
            ms.append(new.strip())
        st.rerun()
    if st.button(f"Save {title.lower()}", key=f"{key}-save"):
        config.save_env({env_name: ",".join(ms)})
        st.success("Saved. The next run uses this order.")


with tabs[1]:
    c1, c2 = st.columns(2)
    with c1:
        model_editor("Free models", "OPENROUTER_MODELS", "free")
    with c2:
        model_editor("Paid fallback models", "OPENROUTER_PAID_FALLBACK", "paid")
    st.divider()
    if st.button("Check models now", disabled=common.key_missing()):
        rows, table = [], st.empty()

        def on_result(r):
            rows.append({"tier": r["tier"], "model": r["model"], "result": "OK" if r["ok"] else "FAIL",
                         "seconds": r["latency_s"], "error": r["error"] or ""})
            table.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        with st.spinner("Trying the models one by one (free first)..."):
            try:
                sel = llm.select_model(force=True, on_result=on_result)
                st.session_state["llm_health"] = {"ok": True, "model": sel["model"]}
                st.success(f"Selected: {sel['model']} ({sel['tier']} tier)")
            except llm.LLMUnavailable as e:
                st.session_state["llm_health"] = {"ok": False, "error": str(e)}
                st.error("No model answered. Try again later or add a paid fallback model.")

# ------------------------------------------------------------------ notifications
with tabs[2]:
    st.markdown("**Telegram**")
    with st.expander("How to create the bot (2 minutes)"):
        st.markdown("1. In Telegram open **@BotFather**, send `/newbot`, follow the steps and copy the token.\n"
                    "2. Paste the token below and save.\n3. Open your new bot, press **Start** and send `hi`.\n"
                    "4. Press **Find my chat id**, then save and send a test message.")
    st.caption(f"Token: {secret_status('TELEGRAM_BOT_TOKEN')}   Chat id: {secret_status('TELEGRAM_CHAT_ID')}")
    tok = st.text_input("Bot token", type="password", key="tg_tok", placeholder="leave empty to keep the saved one")
    chat = st.text_input("Chat id", value=st.session_state.get("tg_found") or config.get("TELEGRAM_CHAT_ID"))
    a, b, c = st.columns(3)
    if a.button("Find my chat id"):
        r = notify.find_chat_id(tok.strip() or config.get("TELEGRAM_BOT_TOKEN"))
        if r.get("ok"):
            st.session_state["tg_found"] = str(r["chat_id"])
            st.rerun()
        else:
            st.error(r.get("detail") or "Not found. Send a message to your bot first.")
    if b.button("Save Telegram"):
        upd = {"TELEGRAM_CHAT_ID": chat.strip()}
        if tok.strip():
            upd["TELEGRAM_BOT_TOKEN"] = tok.strip()
        config.save_env(upd)
        st.success("Saved.")
    if c.button("Send test message"):
        r = notify.send_telegram("Test from AI Hiring Agent - Telegram works.")
        (st.success if r["ok"] else st.error)(r["detail"])
    st.markdown("**Email (optional)**")
    e1, e2 = st.columns(2)
    host = e1.text_input("SMTP host", value=config.get("SMTP_HOST"), key="smtp_host")
    port = e2.text_input("SMTP port", value=config.get("SMTP_PORT", "587"), key="smtp_port")
    user = e1.text_input("SMTP user", value=config.get("SMTP_USER"), key="smtp_user")
    pw = e2.text_input("SMTP password / app password", type="password", key="smtp_pw", placeholder="leave empty to keep")
    to = st.text_input("Send digests to", value=config.get("EMAIL_TO"), key="email_to")
    a, b = st.columns(2)
    if a.button("Save email"):
        upd = {"SMTP_HOST": host.strip(), "SMTP_PORT": port.strip(), "SMTP_USER": user.strip(), "EMAIL_TO": to.strip()}
        if pw.strip():
            upd["SMTP_PASSWORD"] = pw.strip()
        config.save_env(upd)
        st.success("Saved.")
    if b.button("Send test email"):
        r = notify.send_email("Test from AI Hiring Agent", "Email works.")
        (st.success if r["ok"] else st.error)(r["detail"])

# ------------------------------------------------------------------ other settings
with tabs[3]:
    fc = st.text_input("Firecrawl key (optional, fetches full job texts)", type="password", key="fc_key",
                       placeholder=f"{secret_status('FIRECRAWL_API_KEY')} - leave empty to keep")
    daily = st.text_input("Daily run time (HH:MM)", value=config.get("DAILY_TIME", "20:00"), key="daily_time")
    maxe = st.number_input("Most jobs ranked per run", 1, 200, int(config.get("MAX_EVALS_PER_RUN", "20") or 20), key="max_evals")
    lim = st.number_input("Monthly spend limit in USD (0 = no guard)", 0.0, 1000.0,
                          float(config.get("MONTHLY_SPEND_LIMIT_USD", "5") or 0), step=1.0, key="spend_limit")
    rm = st.text_input("Resume-Matcher models (comma separated)", value=config.get("RESUME_MATCHER_MODELS", "xiaomi/mimo-v2.6-flash"), key="rm_models")
    if st.button("Save settings"):
        from brain import schedule
        try:
            schedule.parse_time(daily)
        except ValueError as e:
            st.error(str(e))
        else:
            upd = {"DAILY_TIME": daily.strip(), "MAX_EVALS_PER_RUN": int(maxe), "MONTHLY_SPEND_LIMIT_USD": lim, "RESUME_MATCHER_MODELS": rm.strip()}
            if fc.strip():
                upd["FIRECRAWL_API_KEY"] = fc.strip()
            config.save_env(upd)
            st.success("Saved. A changed daily time takes effect after you re-install the schedule (Schedule page).")

# ------------------------------------------------------------------ doctor
with tabs[4]:
    deep = st.checkbox("Also make one real model call (slower)")
    if st.button("Run checks"):
        with st.spinner("Checking..."):
            res = doctor.run(llm=deep)
        s = doctor.summary(res)
        st.write(f"**{s['PASS']} passed, {s['WARN']} warnings, {s['FAIL']} failed**")
        icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}
        st.dataframe(pd.DataFrame([{"": icon[r["status"]], "check": r["name"], "result": r["detail"], "how to fix": r["fix"]} for r in res]),
                     use_container_width=True, hide_index=True)
