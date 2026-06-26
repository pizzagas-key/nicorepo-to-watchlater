#!/usr/bin/env python3
"""
ニコレポ → あとでみる 自動登録スクリプト

使用方法:
  python3 nicorepo_to_watchlater.py --pages 3
  python3 nicorepo_to_watchlater.py --count 20
  python3 nicorepo_to_watchlater.py --save-credentials   # 認証情報を暗号化して保存
"""

import argparse
import base64
import getpass
import json
import os
import secrets
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

# ========== ファイルパス ==========
SCRIPT_DIR = Path(__file__).parent
STATE_FILE      = SCRIPT_DIR / "watchlater_added.json"  # 登録済み動画ID
CREDENTIALS_FILE = SCRIPT_DIR / ".nico_credentials"      # 暗号化済み認証情報
SESSION_FILE    = SCRIPT_DIR / ".nico_session"            # キャッシュセッション

# ========== ニコニコ API 設定 ==========
BASE_HEADERS = {
    "X-Frontend-Id": "6",
    "X-Frontend-Version": "0",
    "User-Agent": "nicorepo-watchlater/1.0",
}
LOGIN_URL       = "https://account.nicovideo.jp/login/redirector"
FEED_URL        = "https://api.feed.nicovideo.jp/v1/activities/followings/all"
WATCH_LATER_URL = "https://nvapi.nicovideo.jp/v1/users/me/watch-later"
REQUEST_INTERVAL = 1.5  # サーバー負荷軽減のためのリクエスト間隔（秒）


# ============================================================
# 暗号化ユーティリティ
# ============================================================

def _derive_key(master_password: str, salt: bytes) -> bytes:
    """マスターパスワード + salt から Fernet キーを導出する（PBKDF2-HMAC-SHA256）"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,   # OWASP 推奨値
    )
    return base64.urlsafe_b64encode(kdf.derive(master_password.encode()))


def save_credentials(email: str, password: str, master_password: str):
    """メール・パスワードをマスターパスワードで暗号化して保存する"""
    salt = os.urandom(16)
    key  = _derive_key(master_password, salt)
    f    = Fernet(key)
    payload = json.dumps({"email": email, "password": password}).encode()
    token   = f.encrypt(payload)

    data = {
        "salt":  base64.b64encode(salt).decode(),
        "token": token.decode(),
    }
    with open(CREDENTIALS_FILE, "w") as fp:
        json.dump(data, fp)
    os.chmod(CREDENTIALS_FILE, 0o600)
    print(f"[INFO] 認証情報を暗号化して保存しました: {CREDENTIALS_FILE}")


def load_credentials(master_password: str) -> tuple[str, str] | None:
    """暗号化された認証情報を復号して (email, password) を返す。失敗時は None"""
    if not CREDENTIALS_FILE.exists():
        return None
    with open(CREDENTIALS_FILE, "r") as fp:
        data = json.load(fp)
    salt  = base64.b64decode(data["salt"])
    token = data["token"].encode()
    key   = _derive_key(master_password, salt)
    try:
        payload = Fernet(key).decrypt(token)
        creds   = json.loads(payload)
        return creds["email"], creds["password"]
    except InvalidToken:
        return None


# ============================================================
# セッション管理
# ============================================================

def save_session(user_session: str):
    with open(SESSION_FILE, "w") as f:
        f.write(user_session.strip())
    os.chmod(SESSION_FILE, 0o600)


def load_session() -> str | None:
    if SESSION_FILE.exists():
        s = SESSION_FILE.read_text().strip()
        return s or None
    return None


def clear_session():
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()


# ============================================================
# ニコニコ ログイン
# ============================================================

def login(email: str, password: str) -> str | None:
    """ログインして user_session を返す。失敗時は None"""
    sess = requests.Session()
    resp = sess.post(
        LOGIN_URL,
        data={"mail_tel": email, "password": password},
        allow_redirects=True,
    )
    locs = [r.headers.get("Location", "") for r in resp.history]
    if any("cant_login" in loc for loc in locs):
        return None
    return sess.cookies.get("user_session")


def verify_session(user_session: str) -> bool:
    """セッションが有効かどうかを確認する（フィードAPIに軽くアクセス）"""
    sess = requests.Session()
    sess.cookies.set("user_session", user_session, domain=".nicovideo.jp")
    try:
        resp = sess.get(
            FEED_URL,
            params={"context": "my_timeline"},
            headers=BASE_HEADERS,
            timeout=10,
        )
        return resp.status_code == 200
    except requests.RequestException:
        return False


def get_session(args) -> tuple[str, str | None]:
    """
    有効な user_session を取得する。
    戻り値: (user_session, master_password_or_None)

    優先順位:
      1. --session 引数（そのまま使用）
      2. キャッシュ済みセッション（有効期限チェックあり）
      3. 保存済み認証情報で自動ログイン
      4. 対話入力でログイン → 認証情報を保存するか確認
    """

    # 1. --session 引数（非推奨: ps aux でセッション値が他ユーザーに見える）
    if args.session:
        print("[WARN] --session はセキュリティ上非推奨です。ps aux で他ユーザーにセッション値が見える可能性があります。")
        print("       代わりに --save-credentials を使ってください。")
        return args.session, None

    # 2. キャッシュセッションが有効なら使う
    cached = load_session()
    if cached:
        print("[INFO] キャッシュセッションを確認中...", end=" ", flush=True)
        if verify_session(cached):
            print("有効")
            return cached, None
        print("期限切れ → 再ログインします")
        clear_session()

    # 3. 暗号化済み認証情報で自動ログイン
    if CREDENTIALS_FILE.exists():
        master_pw = _get_master_password(confirm=False)
        creds = load_credentials(master_pw)
        if creds is None:
            print("[WARN] マスターパスワードが違います。対話入力に切り替えます。")
        else:
            email, password = creds
            print(f"[INFO] 保存済み認証情報でログイン中 ({email})...", end=" ", flush=True)
            us = login(email, password)
            if us:
                print("成功")
                save_session(us)
                return us, master_pw
            print("失敗（パスワードが変わった可能性があります）")
            print("[INFO] 認証情報を再登録してください: --save-credentials")
            sys.exit(1)

    # 4. 対話入力
    print("ニコニコアカウント情報を入力してください")
    email    = input("  メールアドレス: ").strip()
    password = getpass.getpass("  パスワード    : ")

    print("[INFO] ログイン中...", end=" ", flush=True)
    us = login(email, password)
    if not us:
        sys.exit("\n[ERROR] ログインに失敗しました。")
    print("成功")
    save_session(us)

    # 認証情報を保存するか確認
    ans = input("認証情報を暗号化して保存しますか？ [Y/n]: ").strip().lower()
    if ans in ("", "y"):
        master_pw = _get_master_password(confirm=True)
        save_credentials(email, password, master_pw)
        return us, master_pw

    return us, None


def _get_master_password(confirm: bool) -> str:
    """マスターパスワードを対話入力する（confirm=True なら2回入力）"""
    while True:
        pw = getpass.getpass("  マスターパスワード（暗号化キー）: ")
        if not pw:
            print("  [WARN] 空のパスワードは設定できません")
            continue
        if confirm:
            pw2 = getpass.getpass("  マスターパスワード（確認）      : ")
            if pw != pw2:
                print("  [WARN] パスワードが一致しません")
                continue
        return pw


# ============================================================
# ニコレポ取得
# ============================================================

def generate_action_track_id() -> str:
    chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(secrets.choice(chars) for _ in range(10)) + f"_{int(time.time() * 1000)}"


def fetch_feed_page(
    sess: requests.Session,
    cursor: str | None,
) -> dict:
    """
    フォロー新着フィードを1ページ分取得する。
    cursor: ページネーション用カーソル（Noneなら最新ページ）
    戻り値: {activities: [...], nextCursor: str|None, code: str}
    """
    params: dict = {"context": "my_timeline"}
    if cursor:
        params["cursor"] = cursor
    resp = sess.get(
        FEED_URL,
        params=params,
        headers=BASE_HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def collect_video_ids(
    sess: requests.Session,
    max_pages: int | None,
    max_count: int | None,
    last_max_id: str | None = None,
) -> tuple[list[str], str | None]:
    """
    フォロー新着フィードから動画IDをページネーションしながら収集する。

    last_max_id が指定された場合、そのアクティビティIDに到達したら取得を停止する。
    アクティビティIDはタイムスタンプ先頭のため、これが前回実行済みの境界になる。

    戻り値: (video_ids, new_max_id)
      new_max_id: 今回取得した中で最も新しいアクティビティID（次回の停止点として使う）
    """
    video_ids: list[str] = []
    cursor: str | None = None
    new_max_id: str | None = None  # 1ページ目の先頭アクティビティID
    page = 0
    stopped_early = False

    while True:
        if max_pages is not None and page >= max_pages:
            break
        if max_count is not None and len(video_ids) >= max_count:
            break

        print(f"  [フィード] ページ {page + 1} 取得中...", end=" ", flush=True)
        try:
            data = fetch_feed_page(sess, cursor)
        except requests.HTTPError as e:
            print(f"\n[ERROR] フィード取得失敗: {e}")
            break

        activities = data.get("activities", [])
        if not activities:
            print("(終端)")
            break

        page_count = 0
        for activity in activities:
            act_id = activity.get("id", "")
            # 前回実行済みの境界に到達したら停止
            if last_max_id and act_id == last_max_id:
                stopped_early = True
                break
            content = activity.get("content", {})
            if content.get("type") == "video":
                vid = content.get("id")
                if vid:
                    video_ids.append(vid)
                    page_count += 1

        # 1ページ目の先頭IDを今回の新規最大IDとして記録
        if page == 0 and activities:
            new_max_id = activities[0].get("id")

        print(f"{page_count}件")

        if stopped_early:
            print("  [フィード] 前回取得済み境界に到達しました")
            break

        cursor = data.get("nextCursor")
        if not cursor:
            print("  [フィード] 最終ページに到達しました")
            break

        page += 1
        time.sleep(REQUEST_INTERVAL)

    if max_count is not None:
        video_ids = video_ids[:max_count]
    return video_ids, new_max_id


# ============================================================
# あとでみる登録
# ============================================================

def add_to_watch_later(sess: requests.Session, video_id: str) -> bool:
    resp = sess.post(
        WATCH_LATER_URL,
        data={"watchId": video_id},
        headers={
            **BASE_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Request-With": "https://www.nicovideo.jp",
        },
    )
    if resp.status_code in (200, 201, 409):  # 409 = 既登録
        return True
    print(f"    [WARN] HTTP {resp.status_code}: {resp.text[:120]}")
    return False


# ============================================================
# 状態管理（登録済みID・実行履歴・sinceId）
# ============================================================

# 実行履歴の最大保持件数
MAX_RUN_HISTORY = 30


def load_state() -> dict:
    """
    状態ファイルを読み込む。
    戻り値: {
        "added_ids": set[str],   # 登録済み動画ID
        "last_max_id": str|None, # 前回取得した最新エントリーID（sinceId として使用）
        "run_history": list,     # 実行履歴（最大 MAX_RUN_HISTORY 件）
    }
    """
    if STATE_FILE.exists():
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return {
            "added_ids":   set(data.get("added_ids", [])),
            "last_max_id": data.get("last_max_id"),
            "run_history": data.get("run_history", []),
        }
    return {"added_ids": set(), "last_max_id": None, "run_history": []}


def save_state(state: dict):
    """状態ファイルを保存する"""
    data = {
        "added_ids":    sorted(state["added_ids"]),
        "last_max_id":  state.get("last_max_id"),
        "run_history":  state.get("run_history", []),
        "last_updated": datetime.now().isoformat(),
    }
    STATE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def record_run(state: dict, fetched: int, registered: int, skipped: int, since_id: str | None, new_max_id: str | None):
    """実行結果を履歴に追記する"""
    entry = {
        "time":        datetime.now().isoformat(timespec="seconds"),
        "since_id":    since_id,      # 今回の取得開始ID（前回のmax_id）
        "new_max_id":  new_max_id,    # 今回取得した最新ID（次回のsinceId）
        "fetched":     fetched,
        "registered":  registered,
        "skipped":     skipped,
    }
    history = state.get("run_history", [])
    history.append(entry)
    state["run_history"] = history[-MAX_RUN_HISTORY:]  # 古いものを削除


# ============================================================
# メイン
# ============================================================

def cmd_save_credentials(_args):
    """--save-credentials: 認証情報を対話入力して保存"""
    print("=== 認証情報の暗号化保存 ===")
    email    = input("  メールアドレス: ").strip()
    password = getpass.getpass("  パスワード    : ")

    print("[INFO] ログイン確認中...", end=" ", flush=True)
    us = login(email, password)
    if not us:
        sys.exit("\n[ERROR] ログインに失敗しました。メール/パスワードを確認してください。")
    print("成功")

    master_pw = _get_master_password(confirm=True)
    save_credentials(email, password, master_pw)
    save_session(us)
    print("[INFO] 次回以降、マスターパスワードを入力するだけで自動ログインします。")


def cmd_run(args):
    """通常実行: ニコレポ取得 → あとでみる登録"""
    if args.pages is None and args.count is None:
        args.pages = 1

    # 状態読み込み
    if args.reset_state:
        if STATE_FILE.exists():
            STATE_FILE.unlink()
        print("[INFO] 登録済みIDの記録をリセットしました")
    state = load_state()
    added_ids   = state["added_ids"]
    last_max_id = state["last_max_id"]
    print(f"[INFO] 登録済み動画ID数: {len(added_ids)}")
    if last_max_id:
        print(f"[INFO] 前回取得済み最新アクティビティID: {last_max_id}（これより新しいものだけ取得）")
    else:
        print("[INFO] 前回実行の記録なし → 全件取得モードで開始")

    # セッション取得（自動再ログイン込み）
    user_session, _ = get_session(args)

    http_sess = requests.Session()
    http_sess.cookies.set("user_session", user_session, domain=".nicovideo.jp")

    # フィード収集（last_max_id で前回取得済み境界を判定）
    stop_id = None if args.ignore_since else last_max_id
    print(f"\n[STEP 1] フォロー新着取得中（pages={args.pages}, count={args.count}）...")
    if stop_id:
        print(f"  ※ アクティビティID={stop_id} に到達したら停止")
    video_ids, new_max_id = collect_video_ids(
        http_sess, args.pages, args.count, last_max_id=stop_id
    )
    print(f"  取得した動画ID: {len(video_ids)}件（フォロー新着「すべて」から動画コンテンツのみ抽出）")

    # 念のため登録済みIDでも二重チェック（sinceId をスキップした場合などの安全弁）
    seen: set[str] = set()
    new_ids: list[str] = []
    skipped = 0
    for vid in video_ids:
        if vid in added_ids or vid in seen:
            skipped += 1
            continue
        new_ids.append(vid)
        seen.add(vid)
    if skipped:
        print(f"  登録済みID照合でスキップ: {skipped}件")
    print(f"  未登録の動画ID: {len(new_ids)}件")

    # 実行履歴を記録（登録処理前に stop_id / new_max_id を残す）
    record_run(state, fetched=len(video_ids), registered=0, skipped=skipped,
               since_id=stop_id, new_max_id=new_max_id)

    if not new_ids:
        print("\n[INFO] 新たに登録する動画はありません。")
        # new_max_id を更新して保存（次回の停止点として使う）
        if new_max_id:
            state["last_max_id"] = new_max_id
        save_state(state)
        return

    if args.dry_run:
        print("\n[DRY-RUN] 登録対象の動画ID（実際には登録しません）:")
        for vid in new_ids:
            print(f"  - {vid}")
        return

    # あとでみる登録
    print(f"\n[STEP 2] あとでみるに登録中...")
    success_count = 0
    fail_ids: list[str] = []

    for i, vid in enumerate(new_ids, 1):
        print(f"  [{i}/{len(new_ids)}] {vid} ... ", end="", flush=True)
        if add_to_watch_later(http_sess, vid):
            added_ids.add(vid)
            success_count += 1
            print("✓")
        else:
            fail_ids.append(vid)
            print("✗ 失敗")
        time.sleep(REQUEST_INTERVAL)

    # 実行履歴の登録数を更新してから保存
    state["run_history"][-1]["registered"] = success_count
    state["run_history"][-1]["skipped"]    = skipped + len(fail_ids)
    if new_max_id:
        state["last_max_id"] = new_max_id
    save_state(state)

    print(f"\n========== 完了 ==========")
    print(f"  登録成功: {success_count}件")
    if fail_ids:
        print(f"  登録失敗: {len(fail_ids)}件 → {', '.join(fail_ids)}")
    print(f"  累計登録済みID数: {len(added_ids)}件")
    if new_max_id:
        print(f"  次回の停止点ID: {new_max_id}")


def main():
    parser = argparse.ArgumentParser(
        description="ニコレポの動画をあとでみるに自動登録するツール",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  初回セットアップ（認証情報を暗号化保存）:
    python3 nicorepo_to_watchlater.py --save-credentials

  通常実行（マスターパスワードを対話入力）:
    python3 nicorepo_to_watchlater.py --pages 2

  cron 用（マスターパスワードをファイルから読む）:
    python3 nicorepo_to_watchlater.py --pages 1 --master-password-file ~/.nico_master
        """,
    )
    parser.add_argument("--save-credentials", action="store_true",
                        help="認証情報（メール・パスワード）を暗号化して保存する")
    parser.add_argument("--pages",  type=int,   default=None, help="取得ページ数")
    parser.add_argument("--count",  type=int,   default=None, help="登録する最大件数")
    parser.add_argument("--type",   choices=["video","all"], default="all",
                        help="（廃止・無効）後方互換のために残しています。常にすべて取得します")
    parser.add_argument("--session", type=str,  default=None,
                        help="user_session を直接指定 [非推奨: ps aux でセッション値が他ユーザーに見える可能性があります]")
    parser.add_argument("--master-password-file", type=str, default=None,
                        help="マスターパスワードをファイルから読む（cron用）")
    parser.add_argument("--ignore-since", action="store_true",
                        help="前回の sinceId を無視して全件取得する（取り直し用）")
    parser.add_argument("--show-history", action="store_true",
                        help="実行履歴を表示して終了する")
    parser.add_argument("--dry-run",     action="store_true", help="登録せず対象IDを表示するだけ")
    parser.add_argument("--reset-state", action="store_true", help="登録済みIDの記録をリセット")
    args = parser.parse_args()

    # --master-password-file が指定されていたら環境変数に注入してget_session内で使えるようにする
    if args.master_password_file:
        pw_file = Path(args.master_password_file).expanduser()
        if not pw_file.exists():
            sys.exit(f"[ERROR] マスターパスワードファイルが見つかりません: {pw_file}")
        # パーミッションチェック: 他ユーザーが読める状態なら拒否
        if pw_file.stat().st_mode & 0o077:
            sys.exit(
                f"[ERROR] パスワードファイルのパーミッションが危険です（他ユーザーが読める可能性があります）: {pw_file}\n"
                f"  以下を実行してアクセス権を制限してください:\n"
                f"    chmod 600 {pw_file}"
            )
        os.environ["_NICO_MASTER_PW"] = pw_file.read_text().strip()

    if args.show_history:
        state = load_state()
        history = state.get("run_history", [])
        if not history:
            print("実行履歴はありません。")
        else:
            print(f"{'実行時刻':<22} {'取得':>5} {'登録':>5} {'スキップ':>8}  stopId → new_maxId")
            print("-" * 90)
            for h in history:
                print(
                    f"{h['time']:<22} {h['fetched']:>5} {h['registered']:>5} {h['skipped']:>8}"
                    f"  {h.get('since_id') or '(初回)'} → {h.get('new_max_id') or '-'}"
                )
        return

    if args.save_credentials:
        cmd_save_credentials(args)
    else:
        cmd_run(args)


# _get_master_password をファイル対応版に差し替え
_orig_get_master_password = _get_master_password

def _get_master_password(confirm: bool) -> str:
    env_pw = os.environ.get("_NICO_MASTER_PW")
    if env_pw and not confirm:
        return env_pw
    return _orig_get_master_password(confirm)


if __name__ == "__main__":
    main()
