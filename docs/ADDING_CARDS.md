# カード・効果の追加方法

## 新カードの追加

`data/cards.json` にエントリを追加するだけ。

### ユニットカード

```json
{
  "id": "my_unit",
  "name": "My Unit",
  "cost": 3,
  "card_type": "unit",
  "tags": ["creature"],
  "template": "Vanilla",
  "params": {"atk": 3, "hp": 3},
  "rarity": "common"
}
```

必須フィールド:
- `id`: 一意の文字列（デッキJSONで参照）
- `name`: 表示名
- `cost`: マナコスト（0〜10）
- `card_type`: `"unit"` or `"spell"`
- `template`: 効果テンプレート名（`effects.py`のレジストリに登録済みのもの）
- `params`: テンプレートに渡すパラメータ。ユニットは`atk`と`hp`が必須

### スペルカード

```json
{
  "id": "my_spell",
  "name": "My Spell",
  "cost": 2,
  "card_type": "spell",
  "tags": ["damage"],
  "template": "DamagePlayer",
  "params": {"amount": 4},
  "rarity": "uncommon"
}
```

## 利用可能なテンプレート

| テンプレート | パラメータ | 対象 | 説明 |
|-------------|-----------|------|------|
| `Vanilla` | `atk`, `hp` | unit | 追加効果なし |
| `OnPlayDamagePlayer` | `atk`, `hp`, `amount` | unit | 登場時に相手へ`amount`ダメージ |
| `OnPlayDraw` | `atk`, `hp`, `n` | unit | 登場時に`n`枚ドロー |
| `DamagePlayer` | `amount` | spell | 相手に`amount`ダメージ |
| `HealSelf` | `amount` | spell | 自分を`amount`回復（上限20） |
| `Draw` | `n` | spell | `n`枚ドロー |
| `RemoveUnit` | `max_hp` | spell | 相手のHP`max_hp`以下のユニット1体除去 |

## 新効果テンプレートの追加

`card_battle/effects.py` にデコレータ付き関数を追加:

```python
@register_effect("NewEffect")
def _new_effect(gs: GameState, player_idx: int, params: dict[str, Any]) -> None:
    # gs.players[player_idx]     = 効果の使用者
    # gs.players[1 - player_idx] = 相手
    # params = カードJSONの"params"がそのまま渡される
    amount = params["amount"]
    gs.players[1 - player_idx].hp -= amount
```

追加後はすぐにカードJSONから`"template": "NewEffect"`で参照可能。

## 新デッキの作成

`data/decks/` に以下の形式のJSONを配置:

```json
{
  "deck_id": "my_deck",
  "entries": [
    {"card_id": "goblin",  "count": 3},
    {"card_id": "soldier", "count": 3},
    ...
  ]
}
```

制約:
- 合計ちょうど **30枚**
- 同一カード最大 **3枚**
- `card_id`は`cards.json`に存在するもの
