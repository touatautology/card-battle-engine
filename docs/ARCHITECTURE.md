# アーキテクチャ

## モジュール依存関係

```
cli.py ──→ loader.py ──→ models.py
  │            │             ↑
  │            └──→ effects.py
  │
  ├──→ engine.py ──→ actions.py ──→ effects.py
  │        │                           │
  │        └──→ models.py ←────────────┘
  │
  ├──→ ai.py ──→ actions.py
  │
  ├──→ simulation.py ──→ engine.py, ai.py
  │
  └──→ display.py ──→ models.py, actions.py
```

## 設計判断

### GameStateはmutable・直接変更
- **理由**: コードがシンプル、メモリ割り当てが少ない
- **代替案**: 不変GameState + 差分適用 → v0.1には過剰
- AI試行時は`copy.deepcopy`で安全にコピー

### 効果はデコレータベースのレジストリ
```python
@register_effect("DamagePlayer")
def _damage_player(gs, player_idx, params):
    ...
```
- **理由**: 新効果の追加がデコレータ1つで完結
- テンプレート名はカードJSON内で参照される文字列キー

### スタックなし・即時解決
- **理由**: v0.1では効果の打ち消しや連鎖がないため不要
- 効果はGameStateを直接変更して即座に反映

### ブロック（戦闘防御）なし
- **理由**: v0.1のスコープ削減。攻撃は全て相手プレイヤーへの直接ダメージ
- **影響**: アグロ有利のメタ（実測: aggro_rush 79.6% WR）
- v0.2でブロック導入予定

### ターゲット選択なし
- `RemoveUnit`は`hp <= max_hp`の先頭ユニットを除去
- **理由**: AI実装の複雑化を避けつつ決定論性を保証
- v0.2でターゲット指定アクション追加予定

### デッキ30枚・同名最大3枚
- MTGの60/4に対し、小規模MVP向けに縮小
- ゲーム長を適度に保ちつつカード多様性を確保

## データフロー

### 1試合の流れ

```
load_cards() → card_db
load_deck()  → DeckDef ×2
                  ↓
init_game(card_db, deck_a, deck_b, seed)
                  ↓
              GameState（シャッフル済みデッキ、初期手札5枚）
                  ↓
run_game(gs, agents)
    ├── _start_turn(): mana回復、ドロー、ユニット起床
    ├── agent.choose_action(): 合法手から選択
    ├── apply_action(): カードプレイ or 攻撃
    ├── _check_winner(): HP/山札チェック
    └── EndTurnで次のプレイヤーへ
                  ↓
              MatchLog（勝者、ターン数、最終HP）
```

### バッチシミュレーション

```
run_batch(card_db, decks, n_matches, seed)
    ├── combinations(decks, 2)  → 全ペア生成
    ├── 各ペア × n_matches回  → init_game + run_game
    └── match_logs.json 出力
            ↓
aggregate(logs)
    ├── デッキ別 勝率/勝敗/引分
    └── Seat 0/1 勝率
```

## ファイルサイズ目安

| ファイル | 行数 | 役割 |
|---------|------|------|
| models.py | ~100 | 全データ構造 |
| effects.py | ~90 | 効果7種+レジストリ |
| actions.py | ~90 | 行動3種+適用ロジック |
| engine.py | ~120 | ゲームループ |
| ai.py | ~70 | 評価関数+GreedyAI |
| loader.py | ~60 | JSON読み込み+バリデーション |
| simulation.py | ~110 | バッチ+集計 |
| cli.py | ~100 | argparse CLI |
| display.py | ~60 | 表示ユーティリティ |

## 決定論性の保証

1. `random.Random(seed)` インスタンスをGameStateが保持
2. モジュールレベルの`random`は一切使わない
3. 全ての非決定的操作（シャッフル、先手決定）はこのRNGを使用
4. テスト: 同一seed×10回実行で結果が完全一致することを確認
