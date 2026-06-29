# フォロー新着 → あとでみる 自動登録ツール 導入手順

フォローしているユーザーの新着アクティビティを自動的に「あとでみる」へ登録するツールです。
Ubuntu サーバーに SSH 接続して使うことを前提にしています。

---

## 目次

**セットアップ手順**

1. [ファイル構成](#1-ファイル構成)
2. [必要環境](#2-必要環境)
3. [インストール](#3-インストール)
4. [認証情報のセットアップ](#4-認証情報のセットアップ)
5. [動作確認](#5-動作確認)
6. [cron による定期実行](#6-cron-による定期実行)

**補足（セットアップ完了後の参照用）**

- [補足 A. アカウントを変更する](#補足-a-アカウントを変更する)
- [補足 B. アンインストール](#補足-b-アンインストール)
- [補足 C. オプション一覧](#補足-c-オプション一覧)
- [補足 D. 重複排除の仕組み](#補足-d-重複排除の仕組み)
- [補足 E. ログイン機構の詳細](#補足-e-ログイン機構の詳細)
- [補足 F. ファイル一覧と権限](#補足-f-ファイル一覧と権限)
- [補足 G. トラブルシューティング](#補足-g-トラブルシューティング)

---

## 1. ファイル構成

```
~/nicorepo/
├── nicorepo_to_watchlater.py   # メインスクリプト
├── .nico_credentials            # 暗号化済み認証情報（自動生成）
├── .nico_session                # セッションキャッシュ（自動生成）
├── .nico_master                 # マスターパスワード（cron 用・手動作成）
├── watchlater_added.json        # 登録済み動画 ID・実行履歴の記録（自動生成）
└── nicorepo.log                 # cron 実行ログ（自動生成）
```

---

## 2. 必要環境

- Ubuntu 20.04 以降（他の Linux でも動作するはず）
- Python 3.10 以上
- インターネット接続

Python のバージョン確認：

```bash
python3 --version
# Python 3.10.x 以上であること
```

---

## 3. インストール

### 3-1. スクリプトを配置する

```bash
# 作業ディレクトリを作成
mkdir -p ~/nicorepo
cd ~/nicorepo

# スクリプトをコピー（転送済みの場合）
cp /path/to/nicorepo_to_watchlater.py .

# または scp でローカルから転送（接続元PCで実行）
# scp nicorepo_to_watchlater.py ユーザー名@サーバーIP:~/nicorepo/
```

### 3-2. Python ライブラリをインストールする

```bash
# Ubuntu 23.04 以降（pip に制限がある場合）
pip3 install requests cryptography --break-system-packages

# Ubuntu 22.04 以前
pip3 install requests cryptography
```

pip3 が入っていない場合：

```bash
sudo apt update && sudo apt install python3-pip -y
pip3 install requests cryptography
```

---

## 4. 認証情報のセットアップ

ツールのログイン機構は以下の優先順位で動作します。

```
① --session 引数で user_session を直接指定
      ↓ なければ
② キャッシュ済みセッション（.nico_session）を検証して使用
      ↓ 期限切れ・なければ
③ 暗号化済み認証情報（.nico_credentials）で自動再ログイン
      ↓ なければ
④ 対話入力でログイン → 認証情報を保存するか確認
```

**定期実行を完全自動化するには ③ の準備が必要です。**

### 4-1. 認証情報を暗号化して保存する（初回1回だけ）

```bash
cd ~/nicorepo
python3 nicorepo_to_watchlater.py --save-credentials
```

対話形式で以下を入力します：

```
=== 認証情報の暗号化保存 ===
  メールアドレス: your@email.com
  パスワード    : （入力しても表示されません）
[INFO] ログイン確認中... 成功
  マスターパスワード（暗号化キー）: （任意のパスワード）
  マスターパスワード（確認）      : （同じパスワードを再入力）
[INFO] 認証情報を暗号化して保存しました: /home/yourname/nicorepo/.nico_credentials
[INFO] 次回以降、マスターパスワードを入力するだけで自動ログインします。
```

> **マスターパスワードとは？**
> ニコニコのパスワードとは別の、暗号化キー用のパスワードです。
> `.nico_credentials` ファイルを暗号化するために使います。
> 忘れると認証情報を復元できないので注意してください。

### 4-2. cron 用にマスターパスワードをファイルへ保存する

cron はパスワードを対話入力できないため、マスターパスワードをファイルに保存します。

```bash
read -srp "マスターパスワード: " pw && printf '%s' "$pw" > ~/.nico_master && unset pw
chmod 600 ~/.nico_master
```

> `echo 'パスワード' > ファイル` はシェル履歴に平文が残るため使わないでください。
> 上記の `read` コマンドなら入力内容が履歴に残りません。
>
> `.nico_master` は平文ですが、`chmod 600` で所有者のみ読める状態にします。
> `.nico_credentials` はこれとは別に AES で暗号化されているため、
> どちらか一方だけ流出しても認証情報は復元できません。

---

## 5. 動作確認

### 5-1. ドライラン（実際には登録しない）

```bash
cd ~/nicorepo
python3 nicorepo_to_watchlater.py --pages 1 --dry-run
```

マスターパスワードを入力するプロンプトが出るので入力します。
登録対象になる動画 ID が表示されれば OK です。

### 5-2. 実際に登録してみる

```bash
python3 nicorepo_to_watchlater.py --pages 1
```

**初回実行（停止点なし・全件取得）：**

```
[INFO] 登録済み動画ID数: 0
[INFO] 前回実行の記録なし → 全件取得モードで開始
[INFO] キャッシュセッションを確認中... 有効

[STEP 1] フォロー新着取得中（pages=1, count=None）...
  [フィード] ページ 1 取得中... 12件
  取得した動画ID: 12件（フォロー新着「すべて」から動画コンテンツのみ抽出）
  未登録の動画ID: 12件

[STEP 2] あとでみるに登録中...
  [1/12] sm12345678 ... ✓
  [2/12] sm23456789 ... ✓
  ...

========== 完了 ==========
  登録成功: 12件
  累計登録済みID数: 12件
  次回の停止点ID: 1782463467_xxxx_user_xxxxxx
```

**2回目以降（前回の停止点IDで差分のみ取得）：**

```
[INFO] 登録済み動画ID数: 12
[INFO] 前回取得済み最新アクティビティID: 1782463467_xxxx_user_xxxxxx（これより新しいものだけ取得）
[INFO] キャッシュセッションを確認中... 有効

[STEP 1] フォロー新着取得中（pages=1, count=None）...
  ※ アクティビティID=1782463467_xxxx_user_xxxxxx に到達したら停止
  [フィード] ページ 1 取得中... 3件
  [フィード] 前回取得済み境界に到達しました
  取得した動画ID: 3件（フォロー新着「すべて」から動画コンテンツのみ抽出）
  未登録の動画ID: 3件
...
```

### 5-3. 実行履歴を確認する

```bash
python3 nicorepo_to_watchlater.py --show-history
```

```
実行時刻               取得   登録  スキップ  stopId → new_maxId
------------------------------------------------------------------------------------------
2026-06-25T08:00:01      20     12        8  (初回) → 1782463467_xxxx_user_xxxxxx
2026-06-25T14:00:02       3      3        0  1782463467_xxxx → 1782512345_yyyy
2026-06-26T08:00:01       0      0        0  1782512345_yyyy → -
```

---

## 6. cron による定期実行

### 6-1. crontab を編集する

```bash
crontab -e
```

### 6-2. 定期実行の設定例

```cron
# 毎朝 8:00 にフォロー新着10ページ分を処理
0 8 * * * /usr/bin/python3 /home/yourname/nicorepo/nicorepo_to_watchlater.py --pages 10 --master-password-file /home/yourname/.nico_master >> /home/yourname/nicorepo/nicorepo.log 2>&1

# 6時間ごとに実行したい場合
0 */6 * * * /usr/bin/python3 /home/yourname/nicorepo/nicorepo_to_watchlater.py --pages 10 --master-password-file /home/yourname/.nico_master >> /home/yourname/nicorepo/nicorepo.log 2>&1
```

`yourname` は実際のユーザー名に置き換えてください。確認方法：

```bash
whoami       # ユーザー名
which python3  # python3 のパス
```

### 6-3. ログを確認する

```bash
# 最新のログを表示
tail -30 ~/nicorepo/nicorepo.log

# リアルタイムで追う
tail -f ~/nicorepo/nicorepo.log
```

### 6-4. cron が正しく動くか手動テストする

cron はログインシェルと環境が異なるため、cron と同じコマンドを手動実行して確認します。

```bash
/usr/bin/python3 ~/nicorepo/nicorepo_to_watchlater.py \
  --pages 1 \
  --master-password-file ~/.nico_master
```

---

---

> 以下は補足情報です。セットアップ自体には不要ですが、運用時の参考にしてください。

## 補足 A. アカウントを変更する

登録済みの認証情報を別のアカウントに切り替えるには、既存の認証ファイルを削除してから再セットアップします。

```bash
cd ~/nicorepo
rm -f .nico_credentials .nico_session
python3 nicorepo_to_watchlater.py --save-credentials
```

> `watchlater_added.json`（登録済み動画IDの記録）はアカウントをまたいで共有されます。
> 新しいアカウントで一から登録し直したい場合は `--reset-state` も合わせて実行してください。
>
> ```bash
> python3 nicorepo_to_watchlater.py --reset-state
> ```

---

## 補足 B. アンインストール

ツールを完全に削除するには、スクリプトと関連ファイルをすべて削除します。

```bash
# 認証情報・セッション・状態ファイルをまとめて削除
rm -f ~/nicorepo/.nico_credentials \
       ~/nicorepo/.nico_session \
       ~/nicorepo/.nico_master \
       ~/nicorepo/watchlater_added.json \
       ~/nicorepo/nicorepo.log \
       ~/nicorepo/nicorepo_to_watchlater.py

# ディレクトリごと削除する場合
rm -rf ~/nicorepo
```

cron に登録している場合は合わせて削除してください。

```bash
crontab -e
# nicorepo に関する行を削除して保存
```

> `watchlater_added.json` を残しておくと、再インストール後も登録済み動画 ID の記録を引き継げます。

---

## 補足 C. オプション一覧

| オプション | 説明 | 例 |
|---|---|---|
| `--pages N` | フォロー新着を N ページ分取得する | `--pages 3` |
| `--count N` | 未登録のうち最大 N 件まで登録する | `--count 30` |
| `--dry-run` | 登録せず対象 ID を表示するだけ | `--dry-run` |
| `--show-history` | 実行履歴を表示して終了する | `--show-history` |
| `--ignore-since` | 前回の停止点を無視して全件取得する（取り直し用） | `--ignore-since` |
| `--save-credentials` | 認証情報を暗号化して保存する（初回セットアップ） | |
| `--master-password-file` | マスターパスワードをファイルから読む（cron 用） | `--master-password-file ~/.nico_master` |
| `--session` | `user_session` を直接指定する | `--session "user_session_..."` |
| `--reset-state` | 登録済み ID・実行履歴の記録をリセットする | |

`--pages` と `--count` は併用可能で、先に条件を満たした方で停止します。

---

## 補足 D. 重複排除の仕組み

重複処理の防止は2層構造になっています。

### 第1層：停止点IDによる差分取得

実行のたびに取得した最新アクティビティ ID を `watchlater_added.json` の `last_max_id` に保存します。次回実行時はフィードをページネーションしながら取得し、**このIDに到達した時点で取得を停止**することで前回取得済みの範囲を除外します。

```
前回実行
  └─ last_max_id = "1782463467_xxxx_user_xxxxxx" を保存

今回実行
  └─ フィードを先頭から取得
       → "1782463467_xxxx_user_xxxxxx" に到達したら停止
```

### 第2層：ローカル照合（added_ids）

`--ignore-since` で停止点を無視した場合の安全弁として、`added_ids` セットとの照合も行います。すでに登録済みの動画 ID は「あとでみる」への POST 自体をスキップします。

### `watchlater_added.json` の構造

```json
{
  "added_ids": ["sm111", "sm222"],
  "last_max_id": "1782463467_xxxx-xxxx-xxxx_user_xxxxxx",
  "run_history": [
    {
      "time": "2026-06-25T08:00:01",
      "since_id": null,
      "new_max_id": "1782463467_xxxx-xxxx-xxxx_user_xxxxxx",
      "fetched": 20,
      "registered": 12,
      "skipped": 8
    }
  ],
  "last_updated": "2026-06-25T08:00:05"
}
```

実行履歴は最新 30 件まで保持されます。

---

## 補足 E. ログイン機構の詳細

### セッションの自動更新

実行のたびにキャッシュセッション（`.nico_session`）を検証します。
有効なら再ログインせずにそのまま使用し、期限切れなら自動で再ログインします。

```
実行
 │
 ├─ .nico_session が存在する？
 │    ├─ YES → フィード API に試しにアクセス
 │    │          ├─ 200 OK → そのまま使用 ✓
 │    │          └─ エラー → 削除して次へ
 │    └─ NO  → 次へ
 │
 ├─ .nico_credentials が存在する？
 │    ├─ YES → マスターパスワードで復号 → ログイン → .nico_session を更新 ✓
 │    └─ NO  → 次へ
 │
 └─ 対話入力（メール・パスワード）→ ログイン → 保存するか確認
```

### 暗号化の仕組み

`.nico_credentials` は以下の方式で保護されています。

| 項目 | 内容 |
|---|---|
| 暗号化アルゴリズム | AES-128-CBC（Fernet） |
| 鍵導出 | PBKDF2-HMAC-SHA256（反復 480,000 回 / OWASP 推奨値） |
| Salt | 保存ごとにランダム生成（16 バイト） |

マスターパスワードと `.nico_credentials` のどちらか一方だけでは復号できません。

---

## 補足 F. ファイル一覧と権限

| ファイル | 内容 | パーミッション | 暗号化 |
|---|---|---|---|
| `nicorepo_to_watchlater.py` | メインスクリプト | 644 | — |
| `.nico_credentials` | ニコニコのメール・パスワード | **600** | AES（Fernet） |
| `.nico_session` | ログインセッション | **600** | なし |
| `.nico_master` | マスターパスワード（平文） | **600** | なし |
| `watchlater_added.json` | 登録済み動画 ID・停止点ID・実行履歴 | 644 | — |
| `nicorepo.log` | cron 実行ログ | 644 | — |

`.nico_credentials`・`.nico_session` はスクリプトが自動で `chmod 600` を設定します。`.nico_master` は手動での設定が必要です。

---

## 補足 G. トラブルシューティング

### ログインに失敗する

```
[ERROR] ログインに失敗しました。
```

メールアドレス・パスワードを確認してください。
**ニコニコに二段階認証を設定している場合、このスクリプトのパスワードログインは使えません。**
代わりにブラウザでログインして `user_session` を直接指定してください。

```bash
# ブラウザの開発者ツール → Application → Cookies → nicovideo.jp
# → user_session の値をコピーして貼り付ける

python3 nicorepo_to_watchlater.py --session "user_session_12345_xxxxx"
```

> **注意**: `--session` はセキュリティ上非推奨です。コマンドライン引数は `ps aux` で
> 同一サーバーの他ユーザーに見える可能性があります。
> また、`--session` 経由ではセッションが `.nico_session` に保存されないため、
> 実行のたびに指定が必要です。
>
> 二段階認証ユーザーがセッションを保存するには、以下の手順を使います：
>
> ```bash
> # セッション値を一時ファイルに書き込んで読み込む（ファイルは直後に削除）
> echo "user_session_12345_xxxxx" > /tmp/nico_tmp_session
> cat /tmp/nico_tmp_session > ~/nicorepo/.nico_session
> chmod 600 ~/nicorepo/.nico_session
> rm /tmp/nico_tmp_session
> ```
>
> `.nico_session` を手動作成しておくと次回以降は自動でそのセッションを使用します。

---

### マスターパスワードを忘れた

`.nico_credentials` は復号できません。再セットアップしてください。

```bash
cd ~/nicorepo
rm .nico_credentials .nico_session
python3 nicorepo_to_watchlater.py --save-credentials
```

---

### セッション切れのエラーが出る（401 Unauthorized）

```bash
cd ~/nicorepo
rm .nico_session
python3 nicorepo_to_watchlater.py --pages 1
# → マスターパスワード入力 → 自動再ログイン
```

---

### あとでみる登録が失敗する（400 / 500 エラー）

ニコニコ側の API 仕様変更の可能性があります。
`watchlater_added.json` はそのまま残るので、
スクリプトを更新して再実行すれば未登録分だけ処理されます。

---

### 前回より古い範囲も取得し直したい

`--ignore-since` を使うと停止点IDを無視して全件取得します。
登録済み ID の記録（`added_ids`）は消えないため、すでに登録済みの動画は二重登録されません。

```bash
python3 nicorepo_to_watchlater.py --pages 3 --ignore-since
```

---

### 登録済み ID と実行履歴をすべてリセットしたい

```bash
python3 nicorepo_to_watchlater.py --reset-state
```

または手動で削除：

```bash
rm ~/nicorepo/watchlater_added.json
```

---

### cron で動かない

以下を順番に確認してください。

```bash
# 1. python3 のフルパスを確認
which python3

# 2. cron と同じコマンドを手動実行してエラーを確認
/usr/bin/python3 ~/nicorepo/nicorepo_to_watchlater.py \
  --pages 1 --master-password-file ~/.nico_master

# 3. cron のシステムログを確認
grep CRON /var/log/syslog | tail -20
```
