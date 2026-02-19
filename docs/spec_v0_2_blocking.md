# v0.2 仕様書：ブロック（防御）導入

## 1. 目的

- 戦闘で「攻撃側の選択」と「防御側の選択」が発生するようにする
- 複雑化を避け、**1体につき1ブロック（多重ブロックなし）**で固定

## 2. 追加する状態（GameState）

- `phase: "main" | "combat_attack" | "combat_block" | "end"` を追加
- `combat`（一時領域）を追加:
  - `attackers: list[uid]`
  - `blocks: dict[attacker_uid -> blocker_uid]`（未ブロックはキーなし）
  - defender（受け手）は `active_player` の反対側で決まるため、別フィールドは不要

> `board_index` ではなく `UnitInstance.uid` で参照する。除去や死亡でboardが詰まっても参照が壊れない。

## 3. 追加するアクション

| アクション | フェーズ | 説明 |
|-----------|---------|------|
| `GoToCombat()` | main | main → combat_attack へ遷移 |
| `DeclareAttack(attacker_uids: list[int])` | combat_attack | 攻撃するユニットを宣言 |
| `DeclareBlock(pairs: list[tuple[int,int]])` | combat_block | `(blocker_uid, attacker_uid)` のペアを宣言 |

**制約:**
- 同じ `blocker_uid` は1回まで
- 同じ `attacker_uid` は1回まで（1対1ブロック）

既存の `Attack(board_index)` は廃止。

## 4. ターン進行（engine）

### ターン開始（変更なし）
`phase="main"`、マナ更新、ドロー、ユニットを `can_attack=True` に戻す。

### main フェーズ
- `PlayCard`: 現状維持
- `GoToCombat`: `phase="combat_attack"` に遷移
- `EndTurn`: 即ターン終了（戦闘を省略可能）

### combat_attack フェーズ
- `DeclareAttack([...])` を1回だけ実行
- `combat.attackers` をセット
- `phase="combat_block"` に遷移

### combat_block フェーズ
- 防御側エージェントが `DeclareBlock` を1回選択
- `combat.blocks` に反映
- 戦闘解決を実行
- `phase="end"` に遷移

### end フェーズ
- 追加行動なしでターン交代

## 5. 戦闘解決（同時ダメージ）

**同時解決**で統一する。

### 手順

1. ダメージをバッファに積む:
   - `unit_damage: dict[unit_uid -> int]`
   - `player_damage: int`（防御側プレイヤーへの合計）

2. 各 `attacker_uid` について:
   - **未ブロック**: `player_damage += attacker.atk`
   - **ブロック済み**:
     - `unit_damage[blocker_uid] += attacker.atk`
     - `unit_damage[attacker_uid] += blocker.atk`

3. まとめてHP反映:
   - 防御側HPから `player_damage` を引く
   - 各ユニットのhpから `unit_damage` を引く

4. 死亡処理:
   - `hp <= 0` のユニットはboardから除去し、**所有者のgraveyardへ `card_id` を追加**

5. 攻撃したユニットは `can_attack=False` にする（ブロック有無に関係なく）

## 6. 合法手（actions）

`phase` に応じて合法手を切り替える:

| phase | 合法手 |
|-------|--------|
| main | `PlayCard` / `GoToCombat` / `EndTurn` |
| combat_attack | `DeclareAttack(…)` のみ |
| combat_block | 防御側のみ `DeclareBlock(…)` を選択 |

## 7. AI（GreedyAI）最小変更

全探索で「攻撃者集合の冪集合」を列挙すると重いため、v0.2では**攻撃候補を制限**する。

### 攻撃候補（DeclareAttack）
1. 攻撃しない（空集合）
2. 攻撃可能な全員で攻撃
3. 単体攻撃（各ユニット1体ずつ）
4. 「全員−1体」攻撃（各ユニットを1体だけ外すパターン）

### ブロック候補（DeclareBlock）
各attackerに対して「最も得なブロック」を貪欲に選択:
- スコア = **防げるダメージ量** + **相手ユニットを落とせるか** − **自ユニット損失**
- 同じblockerが二重に使われないよう制約

> 既存の「deepcopyで仮実行 → 評価関数で選ぶ」設計を維持する。

## 8. ログ（play_trace）

`GoToCombat` / `DeclareAttack` / `DeclareBlock` が trace に出るようにする（既存のtraceと同形式）。

## 9. 受け入れ基準

- [ ] 未ブロックの攻撃はv0.1同様にプレイヤーへ通る
- [ ] ブロック時はユニット同士で同時に殴り合い、死亡したユニットがgraveyardへ移る
- [ ] 1ブロック1攻撃の制約が破れない
- [ ] 同じseedで結果が再現する（決定論性）
- [ ] 既存の `simulate` / `stats` が動き続ける
- [ ] 全既存テストが通る（アクション変更分は修正）

## 10. 影響を受けるファイル

| ファイル | 変更内容 |
|---------|---------|
| `models.py` | `CombatState` dataclass追加、`GameState` に `phase` / `combat` フィールド追加 |
| `actions.py` | `Attack` 廃止、`GoToCombat` / `DeclareAttack` / `DeclareBlock` 追加、`get_legal_actions` のphase分岐 |
| `engine.py` | ターン進行のphase制御、戦闘解決ロジック、死亡処理 |
| `ai.py` | 攻撃候補生成、ブロック候補の貪欲選択 |
| `display.py` | 戦闘フェーズの表示 |
| `cli.py` | 変更なし（既存CLIそのまま） |
| `effects.py` | 変更なし |
| `loader.py` | 変更なし |
| `simulation.py` | 変更なし |
| `tests/*` | `test_actions.py` / `test_engine.py` / `test_ai.py` / `test_determinism.py` を更新 |
