# Venue Emoji Classification Metric

Each pub is assigned a venue emoji based on a scored keyword match across
its **name** (weight ×3) and **promotion descriptions** (weight ×1).
The highest-scoring category wins.

## Categories

| Emoji | Type | Name signals | Description signals |
|---|---|---|---|
| 🍺 | Craft/Ale | beerhall, brewery, alehouse | real ale, cask ale, craft beer, IPA, tank-fresh |
| 🍷 | Wine bar | wine bar, vino | wine, lillet, rosé, prosecco, sparkling wine, fizz |
| 🍸 | Cocktail bar | cocktail bar, mixology | cocktail, mojito, martini, two-for-one cocktail |
| 🥃 | Spirits/Whisky | whisky bar, spirits bar | whisky, bourbon, jameson, scotch, rum |
| 🎵 | Music venue | music venue, live music | live music, dj, karaoke, rapper, band |
| ⚽ | Sports bar | sports bar | six nations, world cup, football, rugby, live sports, screen |
| 🍽️ | Gastropub | kitchen, dining, gastropub | two courses, brunch, lunch deal, sunday roast |
| ☕ | Cafe | cafe, coffee | coffee, espresso, latte |
| 🍻 | Traditional pub | — | default — no strong signals |

## Research Agent Instructions

For each pub, output a `venue_type` field (one of the types above) based on:
1. The pub's About/description page
2. Drink types and events it promotes
3. Menu signals (food-led → 🍽️, wine list → 🍷, etc.)

This will replace the current heuristic classifier.
