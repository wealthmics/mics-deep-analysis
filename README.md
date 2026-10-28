# mics-deep-analysis
## Stock cycle: how the reading is kept reliable

The page answers two questions separately, because one rule cannot answer both well.

**Where is the stock now?** `stages.py` reads the four-stage model (1 Basing, 2 Advancing,
3 Topping, 4 Declining) from finished weekly closes against the 30-week average. A stage
changes only after two weeks in a row point the same way, and a base or top only resolves
once the price breaks out of its range, so one odd week cannot flip it. The 50-day EMA,
the 200-day average and the golden or death cross are shown as the early warning. A stage
once decided never changes when new prices arrive.

**What usually comes next?** For the current stage, the page counts what followed every
past stage of the same kind for this stock, how long they lasted and where the price was
13 and 26 weeks later, with the number of cases next to every figure, and lists the exact
levels that would turn the stage up or down.

**How did past cycles play out?** `cycle.py` dates the big swings with a volatility-scaled
filter (Lunde and Timmermann style). The fall that ends a bull swing is the same log move
as the rise that ends a bear swing (a 35% rise pairs with a 25.9% fall), so bear swings
are no longer harder to confirm than bull swings.

Every page also checks the price data (unrecorded splits, frozen prices, gaps, stale
closes, short history), compares market-wide falls with the listing's own index, and
shows a High, Medium or Low confidence with the reasons.

- `python -m pytest tests` checks these promises, including that stages and turning
  points never move when new prices arrive. It runs on every push.
- `python calibrate.py` runs everything across a mixed universe and summarises cycles per
  decade, whipsaws, stage changes per year and short stages. Run it before changing any
  setting in `cycle.py` or `stages.py`.
