# Card Battle Engine v0.1

MTG風カードゲームエンジン。CLI上でAI同士の対戦・バッチシミュレーション・統計分析が可能。

## クイックスタート

```bash
# AI vs AI 1試合
python3 -m card_battle play \
  --deck-a data/decks/aggro_rush.json \
  --deck-b data/decks/control_mage.json \
  --seed 42

# 1000試合バッチシミュレーション（ラウンドロビン）
python3 -m card_battle simulate \
  --decks data/decks/*.json \
  --matches 334 --seed 42 \
  --round-robin --output output/run1

# 統計確認
python3 -m card_battle stats --logs output/run1/match_logs.json

# テスト実行
python3 -m unittest discover tests/ -v
```

## プロジェクト構成

```
card-battle-engine/
├── card_battle/
│   ├── models.py       # データクラス（Card, GameState等）
│   ├── effects.py      # 効果テンプレート（7種）
│   ├── actions.py      # 行動定義・合法手生成・適用
│   ├── engine.py       # ゲームループ・勝敗判定
│   ├── ai.py           # GreedyAI / HumanAgent
│   ├── loader.py       # JSON読み込み・バリデーション
│   ├── simulation.py   # バッチ対戦・集計
│   ├── display.py      # CLI表示
│   └── cli.py          # argparse CLI
├── data/
│   ├── cards.json      # カード定義（20種）
│   └── decks/          # サンプルデッキ（3種×30枚）
├── tests/              # ユニットテスト（58件）
└── output/             # 実行時出力
```

## ゲームルール

| 項目 | 仕様 |
|------|------|
| プレイヤーHP | 初期20、上限20 |
| デッキ | 30枚、同名最大3枚 |
| 初期手札 | 5枚 |
| マナ | 毎ターン上限+1（最大10）、ターン開始時に全回復 |
| 場の上限 | ユニット7体 |
| 召喚酔い | ユニットは出したターン攻撃不可 |
| 攻撃 | 相手プレイヤーへ直接ダメージ（v0.1はブロックなし） |
| 勝利条件 | 相手HP≤0、または相手山札切れ |
| 引き分け | 50ターン経過時HP比較、同値ならDraw |

## カード一覧

### ユニット（14種）

| ID | 名前 | コスト | ATK/HP | 効果 | レアリティ |
|----|------|--------|--------|------|-----------|
| goblin | Goblin | 1 | 2/1 | — | common |
| scout | Scout | 1 | 1/2 | — | common |
| soldier | Soldier | 2 | 2/2 | — | common |
| wolf | Wolf | 2 | 3/1 | — | common |
| raider | Raider | 2 | 1/1 | 登場時: 相手に1ダメージ | common |
| knight | Knight | 3 | 3/3 | — | common |
| bear | Bear | 3 | 4/2 | — | common |
| berserker | Berserker | 3 | 5/1 | — | uncommon |
| fire_imp | Fire Imp | 3 | 2/2 | 登場時: 相手に2ダメージ | uncommon |
| ogre | Ogre | 4 | 4/4 | — | common |
| sage | Sage | 4 | 2/3 | 登場時: 1枚ドロー | uncommon |
| scholar | Scholar | 5 | 3/4 | 登場時: 2枚ドロー | rare |
| giant | Giant | 6 | 6/6 | — | uncommon |
| dragon | Dragon | 7 | 7/7 | — | rare |

### スペル（6種）

| ID | 名前 | コスト | 効果 | レアリティ |
|----|------|--------|------|-----------|
| zap | Zap | 1 | 相手に1ダメージ | common |
| bolt | Lightning Bolt | 1 | 相手に3ダメージ | common |
| heal | Healing Light | 2 | 自分を5回復（上限20） | common |
| arcane_intel | Arcane Intellect | 3 | 2枚ドロー | common |
| smite | Smite | 3 | 相手のHP4以下のユニット1体除去 | uncommon |
| fireball | Fireball | 4 | 相手に6ダメージ | uncommon |

## サンプルデッキ

| デッキ | コンセプト | 構成 |
|--------|-----------|------|
| aggro_rush | 低コスト速攻 | 1-3コスト中心、バーンスペル多め |
| control_mage | 後半制圧 | ドロー・回復・除去+大型ユニット |
| midrange | バランス型 | 中コスト主体、攻守両面 |

## AI（GreedyAI）

各合法手を`deepcopy`で仮実行し、評価関数でスコアリング。最高スコアの手を選択。

**評価関数の重み:**

| 要素 | 重み |
|------|------|
| 相手HP減少 | +3.0 |
| 自HP減少 | -2.0 |
| 自盤面ATK合計 | +1.5 |
| 相手盤面ATK合計 | -1.5 |
| 自盤面HP合計 | +0.5 |
| 相手盤面HP合計 | -0.5 |
| 手札枚数 | +0.5 |
| 即勝/即死 | ±1000 |

## CLIコマンド

### `play` — 1試合実行

```bash
python3 -m card_battle play \
  --deck-a <path> --deck-b <path> \
  --seed 42 \
  --mode ava    # ava / hva / hvh
  --trace       # アクションログ出力
```

### `simulate` — バッチ対戦

```bash
python3 -m card_battle simulate \
  --decks data/decks/*.json \
  --matches 500 \
  --seed 42 \
  --round-robin \
  --output output/ \
  --trace         # play_traceをログに含める
```

### `stats` — ログ集計

```bash
python3 -m card_battle stats --logs output/match_logs.json
```

## 動作要件

- Python 3.11+
- 外部依存なし（stdlib only）

## テスト

```bash
# 全テスト
python3 -m unittest discover tests/ -v

# 決定論テストのみ
python3 -m unittest tests.test_determinism -v
```

58テスト、全パス。1000試合クラッシュなしテスト含む。
