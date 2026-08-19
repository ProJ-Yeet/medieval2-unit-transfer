"""Track Mylae's m2tw-editor, which has no releases and commits straight to main.

    python tools/upstream_sync.py status     # what the manifest says today
    python tools/upstream_sync.py triage     # file new upstream files as untriaged
    python tools/upstream_sync.py sync       # what changed since we last looked
    python tools/upstream_sync.py sync --accept   # …and mark it as looked at

The reference tool ships no tags, no releases and no branches: every change lands
on `main`, auto-pushed from the Base44 builder under the message "File changes".
The messages therefore carry nothing — **this tool reads diffs and never commit
subjects.**

His history is mirrored into our own repo under `refs/upstream/editor/*`, so it
survives a force-push or the repo being deleted, and no branch of ours is
touched by it. `merge/PORT_MANIFEST.json` then records what we intend to do with
each of his files:

  port-concept  he knows something we want to rebuild in our stack. A change
                here may mean the FORMAT KNOWLEDGE changed — the loudest signal
                this tool emits, because our Python parser may now be wrong.
  audit         we already do this; compare and take the small wins.
  skip          boilerplate, cloud plumbing, or something we own outright.
  out-of-scope  excluded from V2 (see ROADMAP.md) — includes everything
                AI/autogenerate, which is a permanent no.

`sync` diffs `reviewed_sha..upstream/main`, buckets every changed path by its
disposition, and writes a dated entry to `merge/SYNC_LOG.md`. Files he adds that
the manifest has never seen are reported as **untriaged** and must be given a
disposition by hand — that is the one thing this tool will not guess for you
after the initial pass.

Run it weekly, and always before starting a phase that ports from a directory he
has been working in.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "merge" / "PORT_MANIFEST.json"
SYNC_LOG = ROOT / "merge" / "SYNC_LOG.md"

REMOTE = "upstream-editor"
REF = "refs/upstream/editor/main"
CLONE_URL = "https://github.com/Machiavello-1441/m2tw-editor.git"

DISPOSITIONS = {
    "port-concept": "rebuild the idea in our stack; a change here may mean the "
                    "format knowledge changed",
    "audit": "we already do this — compare and take the small wins",
    "skip": "boilerplate, cloud plumbing, or something we own outright",
    "out-of-scope": "excluded from V2 (ROADMAP.md); AI/autogenerate is permanent",
    "untriaged": "new upstream file nobody has classified yet",
}

# ---------------------------------------------------------------------------
# default triage
# ---------------------------------------------------------------------------
#: (path regex, disposition, phases, reason). FIRST MATCH WINS, so the specific
#: rules sit above the directory-wide ones. These are defaults for files nobody
#: has looked at; a decision already in the manifest is never overwritten.
RULES: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    # --- the hard no. Anything that generates content goes here and stays. ---
    (r"(LuaAiAssistant|ScriptAIAssistant|SymbolGenerator)", "out-of-scope", (),
     "AI/autogenerate — permanently excluded"),
    (r"(KoppenClimateFetcher|LandCoverFetcher|OsmHistoricTagFetcher|worldCover|"
     r"OverlayMapGenerator|BboxLayerGenerator|BBoxGenerator|FeaturesLayerGenerator|"
     r"autoGroundTypes)",
     "out-of-scope", (), "auto-generates map data from external sources — excluded"),

    # --- explicitly out of V2 (ROADMAP "Explicitly out of scope") ---
    (r"^src/pages/(ScriptEditor|AnimationEditor|UnitCardGenerator|GoatTools|"
     r"LuaScripts|NewMapEditor|Export|AssetsConverter)\.jsx$", "out-of-scope", (),
     "V2 out of scope — future expansion only"),
    (r"^src/components/(newmap|export|lua|anim|animation)/", "out-of-scope", (),
     "V2 out of scope — future expansion only"),
    # NB: the campaign EVENTS tab is deliberately not here. `descr_events.txt` is
    # campaign data the map module edits; the script editor is the thing that was
    # ruled out, and the two only look alike from a distance.
    (r"^src/components/map/(Scripting|ScriptTemplate|ScriptReference|scriptReference|"
     r"scriptAutocomplete)", "out-of-scope", (),
     "script editor — future expansion (Scratch-style block UI)"),
    (r"^src/lib/(casAnimCodec|skeletonPoser|slerpUtils)\.js$", "out-of-scope", (),
     "animation — future expansion"),
    (r"^src/components/assets/PoseEditor", "out-of-scope", (),
     "animation posing — future expansion"),

    # --- cloud plumbing and framework boilerplate ---
    (r"^src/components/ui/", "skip", (), "shadcn/ui boilerplate — we have our own CSS"),
    (r"^src/api/base44Client\.js$|^src/lib/(app-params|AuthContext|query-client|"
     r"PageNotFound|utils)\.jsx?$|UserNotRegisteredError", "skip", (),
     "Base44 auth/cloud plumbing — we are self-hosted"),
    (r"^base44/", "skip", (), "Base44 cloud entity schemas — no cloud in our design"),
    (r"^(package|package-lock|jsconfig|components|tailwind\.config|vite\.config|"
     r"postcss\.config|eslint\.config)", "skip", (), "JS toolchain — we have no build step"),
    (r"^(index\.html|README\.md|\.gitignore)$", "skip", (), "project scaffolding"),
    (r"^src/(App\.jsx|Layout\.jsx|main\.jsx|index\.css|pages\.config\.js|utils/|hooks/)",
     "skip", (), "React app shell — our shell is web/index.html"),
    (r"^src/components/(AppErrorBoundary|ProtectedRoute)", "skip", (), "React app shell"),

    # --- phase 6: strings ---
    (r"(stringsBin|StringsBin)", "port-concept", ("6",), "`.strings.bin` codec"),

    # --- phase 7: triggers/conditions ---
    (r"^src/components/shared/(conditionDefs|ConditionRow|TriggerEditor|"
     r"WhenToTestSelect|effectsDescriptionBuilder|EffectAttributeSelect)",
     "port-concept", ("7",), "trigger/condition grammar shared by traits + ancillaries"),

    # --- phase 8/9: traits, ancillaries ---
    (r"^src/components/traits/|^src/pages/TraitsEditor", "port-concept", ("8",),
     "export_descr_character_traits editor"),
    (r"^src/components/ancillaries/|^src/pages/AncillariesEditor", "port-concept", ("9",),
     "export_descr_ancillaries editor"),

    # --- phase 10: minor files, cultures, characters ---
    # These three live under minorfiles/ but belong to other phases, so they have
    # to be matched before the directory-wide rule below claims them.
    (r"spritesheet|SpriteSheet|sdXml", "port-concept", ("14",),
     "sprite sheet + sd XML editor"),
    (r"banners|Banners", "port-concept", ("11", "14"), "banner textures"),
    (r"^src/components/minorfiles/stratmap/", "port-concept", ("15",),
     "strat map characters"),
    (r"^src/components/minorfiles/|^src/pages/MinorFiles", "port-concept", ("10",),
     "rebel factions / religions / resources / character names"),
    (r"^src/(components/cultures/|pages/CulturesEditor)", "port-concept", ("10",),
     "descr_cultures editor"),
    (r"^src/pages/CharactersEditor", "port-concept", ("10", "15"),
     "descr_character / names"),

    # --- phase 11: factions ---
    (r"^src/components/factions/|^src/pages/FactionsEditor", "port-concept", ("11",),
     "descr_sm_factions, banners, faction strings"),

    # --- phase 12: EDB ---
    (r"^src/components/edb/(EDBParser|EDBExporter|EDBValidator)", "audit", ("12",),
     "their EDB parser vs our buildings.py — compare field coverage"),
    (r"^src/components/edb/|^src/pages/EDBEditor", "port-concept", ("12",),
     "EDB editor UI: collapsible tree, new-tree flow, capability/requirement builders"),

    # --- phase 13: units, sounds, projectiles, mounts (we own these) ---
    (r"^src/components/units/|^src/pages/UnitEditor", "audit", ("13",),
     "their EDU fields/dropdowns vs ours — adopt fields, never their hardcoded vocab"),
    (r"^src/pages/SoundEditor", "audit", ("13",), "their sound editor vs our sounds.py"),
    (r"^src/lib/modeldb(Codec|Store)\.js$", "audit", ("13",),
     "their modeldb codec vs our modeldb.py — we own this format"),

    # --- phase 14: 3D, textures, sprites ---
    (r"^src/lib/(casCodec|ms3dCodec|textureCodec|textureLoader|tgaEncoder)\.js$",
     "port-concept", ("14",), "binary mesh/texture codecs — cross-check vs the Blender addon"),
    (r"^src/components/assets/", "port-concept", ("14",), "3D model + texture viewer"),

    # --- phase 15: campaign map ---
    (r"^src/components/map/|^src/pages/(CampaignMap|CampaignManager|CampaignSettings)|"
     r"^src/components/campaigns?/", "port-concept", ("15",),
     "campaign map + descr_strat — the flagship phase"),
    (r"^src/lib/(mapLayerStore|autoGroundTypes|tgaLoader)\.js$", "port-concept", ("15",),
     "map layer handling"),
    (r"^src/components/minorfiles/stratmap/", "port-concept", ("15",), "strat map characters"),

    # --- phase 5: home / file discovery ---
    (r"^src/components/home/|^src/pages/Home\.jsx$", "port-concept", ("5",),
     "which files they read and how they discover them"),

    # --- leftovers worth a look ---
    (r"^src/components/shared/", "audit", ("4",), "shared UI patterns — Code View may reuse"),
    (r"^src/pages/TextEditor", "audit", ("4",), "raw text editing — informs Code View"),
    (r"^src/lib/", "audit", (), "library code — classify properly when its phase arrives"),
    (r"^src/pages/", "audit", (), "page shell — classify when its phase arrives"),
)


def default_for(path: str) -> tuple[str, tuple[str, ...], str]:
    for pattern, disp, phases, reason in RULES:
        if re.search(pattern, path):
            return disp, phases, reason
    return "untriaged", (), ""


# ---------------------------------------------------------------------------
# git plumbing
# ---------------------------------------------------------------------------
def git(*args: str, check: bool = True) -> str:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"git {' '.join(args)} failed:\n{r.stderr.strip()}")
    return r.stdout.strip()


def ensure_remote() -> None:
    if REMOTE not in git("remote").split():
        print(f"adding remote {REMOTE}")
        git("remote", "add", REMOTE, CLONE_URL)
    # The refspec is what keeps his branches out of ours: they land under
    # refs/upstream/editor/, not refs/remotes/, so nothing of his can ever be
    # mistaken for one of our branches or get merged by accident.
    git("config", f"remote.{REMOTE}.fetch", "+refs/heads/*:refs/upstream/editor/*")


def fetch() -> str:
    ensure_remote()
    print(f"fetching {REMOTE}…")
    git("fetch", REMOTE)
    return git("rev-parse", REF)


def upstream_files(ref: str = REF) -> list[str]:
    return [p for p in git("ls-tree", "-r", "--name-only", ref).splitlines() if p]


def changed(since: str, until: str = REF) -> list[tuple[str, str]]:
    """[(status, path)] between two commits. Status is git's: A/M/D/R…"""
    out = []
    for line in git("diff", "--name-status", f"{since}..{until}").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            # A rename arrives as "R100 old new" — the new path is what we track.
            out.append((parts[0][0], parts[-1]))
    return out


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------
def load() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {"upstream": {"remote": REMOTE, "ref": REF, "clone_url": CLONE_URL,
                         "reviewed_sha": "", "reviewed_date": ""},
            "dispositions": DISPOSITIONS, "files": {}}


def save(m: dict) -> None:
    m["dispositions"] = DISPOSITIONS
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(m, indent=1, ensure_ascii=False) + "\n",
                        encoding="utf-8")


def triage(m: dict, sha: str, *, redo: bool = False) -> tuple[int, int]:
    """File every upstream path. Existing decisions are left alone — this tool
    proposes, a human disposes, and re-running must never silently undo that."""
    added = updated = 0
    for path in upstream_files():
        rec = m["files"].get(path)
        if rec and not redo:
            if rec.get("status") == "gone":       # he brought a deleted file back
                rec["status"] = "triaged"
                updated += 1
            continue
        disp, phases, reason = default_for(path)
        m["files"][path] = {
            "disposition": disp,
            "phases": list(phases),
            "reason": reason,
            "status": "triaged" if disp != "untriaged" else "untriaged",
            "first_seen": sha[:7],
            "notes": (rec or {}).get("notes", ""),
        }
        added += 1
    live = set(upstream_files())
    for path, rec in m["files"].items():
        if path not in live and rec.get("status") != "gone":
            rec["status"] = "gone"                # deleted upstream; keep the record
            updated += 1
    return added, updated


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def cmd_status(args) -> int:
    m = load()
    up = m["upstream"]
    print(f"manifest : {len(m['files'])} files")
    print(f"reviewed : {up['reviewed_sha'][:7] or '(never)'} {up['reviewed_date']}")
    counts: dict[str, int] = {}
    phases: dict[str, int] = {}
    for rec in m["files"].values():
        counts[rec["disposition"]] = counts.get(rec["disposition"], 0) + 1
        for p in rec["phases"]:
            phases[p] = phases.get(p, 0) + 1
    print("\ndisposition:")
    for d, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {d:<13} {n:>4}   {DISPOSITIONS.get(d, '')[:54]}")
    print("\nfiles per phase:")
    for p, n in sorted(phases.items(), key=lambda kv: int(kv[0])):
        print(f"  phase {p:<3} {n:>4}")
    untriaged = [p for p, r in m["files"].items() if r["disposition"] == "untriaged"]
    if untriaged:
        print(f"\nUNTRIAGED ({len(untriaged)}) — give these a disposition by hand:")
        for p in untriaged[:20]:
            print(f"  {p}")
    return 0


def cmd_triage(args) -> int:
    sha = fetch() if not args.no_fetch else git("rev-parse", REF)
    m = load()
    added, updated = triage(m, sha, redo=args.redo)
    if not m["upstream"]["reviewed_sha"]:
        m["upstream"]["reviewed_sha"] = sha
        m["upstream"]["reviewed_date"] = time.strftime("%Y-%m-%d")
    save(m)
    print(f"{added} filed, {updated} updated -> {MANIFEST.relative_to(ROOT)}")
    return cmd_status(args)


def cmd_sync(args) -> int:
    sha = fetch() if not args.no_fetch else git("rev-parse", REF)
    m = load()
    since = m["upstream"]["reviewed_sha"]
    if not since:
        print("no reviewed SHA yet — run `triage` first")
        return 2
    if since == sha:
        print(f"up to date at {sha[:7]} — nothing new since "
              f"{m['upstream']['reviewed_date']}")
        return 0

    delta = changed(since, sha)
    ncommits = git("rev-list", "--count", f"{since}..{sha}")
    buckets: dict[str, list[tuple[str, str]]] = {}
    for st, path in delta:
        rec = m["files"].get(path)
        disp = rec["disposition"] if rec else "untriaged"
        buckets.setdefault(disp, []).append((st, path))

    print(f"\n{since[:7]}..{sha[:7]} — {ncommits} commits, {len(delta)} files changed")
    print("(commit messages are all \"File changes\" upstream; this is diff-driven)\n")

    order = ["port-concept", "audit", "untriaged", "out-of-scope", "skip"]
    lines: list[str] = []
    for disp in order:
        items = buckets.get(disp)
        if not items:
            continue
        head = f"{disp} ({len(items)})"
        print(head)
        lines.append(f"### {head}")
        if disp in ("skip", "out-of-scope"):
            print("  (counted only)")
            lines.append("")
            lines.append("Counted only.")
            lines.append("")
            continue
        for st, path in sorted(items):
            rec = m["files"].get(path, {})
            ph = ",".join(rec.get("phases", [])) or "—"
            # ASCII only past this point: this prints to a Windows console that
            # is cp1252 by default, and an arrow glyph is not worth a traceback.
            flag = ""
            if disp == "port-concept":
                flag = "  <-- FORMAT KNOWLEDGE MAY HAVE CHANGED"
            elif disp == "untriaged":
                flag = "  <-- NEW FILE, needs a disposition"
            print(f"  {st} {path}  [phase {ph}]{flag}")
            lines.append(f"- `{st}` `{path}` — phase {ph}{flag}")
        lines.append("")

    # New files are filed as untriaged so the next `status` keeps nagging until
    # somebody decides what they are.
    added, updated = triage(m, sha)
    if added or updated:
        print(f"\n{added} new file(s) filed as untriaged, {updated} record(s) updated")

    if args.accept:
        entry = "\n".join([f"## {time.strftime('%Y-%m-%d')} — {since[:7]}..{sha[:7]}", "",
                           f"{ncommits} commits, {len(delta)} files changed.", ""]
                          + lines).rstrip()
        SYNC_LOG.write_text(_prepend_entry(entry), encoding="utf-8")
        m["upstream"]["reviewed_sha"] = sha
        m["upstream"]["reviewed_date"] = time.strftime("%Y-%m-%d")
        save(m)
        print(f"\nreviewed SHA -> {sha[:7]}; logged to {SYNC_LOG.relative_to(ROOT)}")
        print("remember to update STATE.md's Upstream line")
    else:
        save(m)
        print("\n(dry run — pass --accept to record this review and bump the SHA)")
    return 0


LOG_HEADER = ("# Upstream sync log\n\n"
              "Every review of Mylae's `main`, newest first. Written by "
              "`tools/upstream_sync.py sync --accept`. His commit messages all say "
              "\"File changes\", so these entries are the only record of what "
              "actually moved.\n")


def _prepend_entry(entry: str) -> str:
    """Newest entry directly under the header — the log is read top-down and the
    interesting review is always the last one."""
    prev = SYNC_LOG.read_text(encoding="utf-8") if SYNC_LOG.exists() else LOG_HEADER
    header, sep, rest = prev.partition("\n## ")
    older = (sep + rest).rstrip()
    return f"{header.rstrip()}\n\n{entry}\n{older}\n" if older else \
           f"{header.rstrip()}\n\n{entry}\n"


def main(argv=None) -> int:
    # The default Windows console is cp1252 and this tool prints paths and em
    # dashes that are not in it. Never let an encoding turn a report into a
    # traceback.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn, helptext in (("status", cmd_status, "what the manifest says"),
                               ("triage", cmd_triage, "file new upstream files"),
                               ("sync", cmd_sync, "what changed since we last looked")):
        p = sub.add_parser(name, help=helptext)
        p.set_defaults(fn=fn)
        if name != "status":
            p.add_argument("--no-fetch", action="store_true",
                           help="use the mirror as it is, don't hit the network")
        if name == "triage":
            p.add_argument("--redo", action="store_true",
                           help="re-apply the default rules over existing decisions "
                                "(throws away hand edits)")
        if name == "sync":
            p.add_argument("--accept", action="store_true",
                           help="record this review: write SYNC_LOG and bump the SHA")
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
