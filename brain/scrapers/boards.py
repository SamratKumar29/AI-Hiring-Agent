"""Run the built-in board scrapers (RemoteOK, Michael Page, Wellfound) for a profile and save into its jobs.db.

A board is used only when the profile has an enabled `board_search` source for it (RemoteOK also when work mode
is remote/any, since its public feed has no per-user URL). Boards we cannot scrape reliably are reported, not faked.
"""
from brain import jobs_db, profiles, sources
from brain.scrapers import michaelpage, remoteok, wellfound

UNSUPPORTED = {
    "naukri": "Naukri answers plain requests with 'recaptcha required' - paste single posting links instead.",
    "indeed": "Indeed blocks automated requests (HTTP 403) - paste single posting links instead.",
    "multirecruit": "MultiRecruit's job list is JavaScript-only (no listings in the HTML) - paste single posting links instead.",
    "linkedin": "Handled by the manual LinkedIn scraper (brain.scrapers.manual) and the Firecrawl stage.",
}


def run(name: str | None = None, per_board: int = 40) -> dict:
    """-> {"boards": {board: {"found": n, "added": n, "error": str|None}}, "unsupported": {board: reason}, "added": n}"""
    name = name or profiles.get_active()
    prefs = profiles.load_profile(name)["prefs"]
    roles = prefs.get("target_roles") or []
    srcs = [s for s in sources.list_sources("board_search", name=name) if s["enabled"]]
    urls = lambda b: [s["url"] for s in srcs if s["board"] == b]  # noqa: E731
    out = {"boards": {}, "unsupported": {}, "added": 0}

    def go(board, fn):
        try:
            rows = fn()
            res = jobs_db.upsert_jobs(rows, name=name)
            out["boards"][board] = {"found": len(rows), "added": res["inserted"], "error": None}
            out["added"] += res["inserted"]
            for s in srcs:
                if s["board"] == board:
                    sources.set_status(s["id"], f"{len(rows)} found, {res['inserted']} new")
        except Exception as e:  # noqa: BLE001
            out["boards"][board] = {"found": 0, "added": 0, "error": str(e)[:200]}

    if urls("remoteok") or str(prefs.get("work_mode", "any")).lower() in ("remote", "any"):
        go("remoteok", lambda: remoteok.fetch(profiles.core_titles(roles) or roles, per_board))
    if urls("michaelpage"):
        go("michaelpage", lambda: michaelpage.fetch(urls("michaelpage"), limit=per_board))
    if urls("wellfound"):
        go("wellfound", lambda: wellfound.fetch(urls("wellfound"), limit=per_board))
    for s in srcs:
        if s["board"] in UNSUPPORTED and s["board"] != "linkedin":
            out["unsupported"][s["board"]] = UNSUPPORTED[s["board"]]
            sources.set_status(s["id"], "not scrapable - " + UNSUPPORTED[s["board"]][:60])
    return out
