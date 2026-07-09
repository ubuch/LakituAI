# War Management

The LakituAI system now supports multiple wars. Each war maintains its own race history, player standings, and cumulative points.

## Quick Start

### Process a race in the current war
```bash
python -m lakituai resources/screenshots/screenshot1.jpg
```
This uses the "default" war (or whichever is set as current). Race counter starts at 1 for each war.

### Process a race in a specific war
```bash
python -m lakituai --war "War 1" resources/screenshots/race_1.jpg
python -m lakituai --war "War 2" resources/screenshots/race_2.jpg
```
The `--war` flag accepts a war name. If the war doesn't exist, it's created automatically.

### Switch active war
When you specify `--war`, it becomes the "current" war. Subsequent runs without `--war` will use the current one.

```bash
# Set "War 1" as current
python -m lakituai --war "War 1" resources/screenshots/screenshot1.jpg

# This now uses "War 1" (race #2)
python -m lakituai resources/screenshots/screenshot2.jpg

# Switch to "War 2"
python -m lakituai --war "War 2" resources/screenshots/screenshot3.jpg

# This now uses "War 2" (race #2)
python -m lakituai resources/screenshots/screenshot4.jpg
```

### List all wars
```bash
python -m lakituai --list-wars
```

Output:
```
================================================================================
WARS
================================================================================

ID #1: War 1
  Created: 2026-07-09 15:22:45
  Races: 12
  Teams: RK, ne

ID #2: War 2
  Created: 2026-07-09 15:25:12
  Races: 12
  Teams: RK, ne
```

### Delete a war
```bash
python -m lakituai --delete-war 1
```
This will prompt for confirmation before deleting war #1 and all its races.

## Data Organization

### SQLite Database
- File: `resources/war.db`
- Schema: Tables for wars, races, race_results, player_standings, team_standings
- All wars stored in single database; each war has unique ID

### Race JSON Files
- Location: `resources/results/`
- Naming: `race_{n}_{TAG1}-{TAG2}_{YYYY_MM_DD}.json`
- Races are numbered per war (race 1, 2, 3, etc. within each war)
- All races from all wars stored in same folder (differentiable by metadata)

### Current War Config
- File: `config/current_war.json`
- Stores the name of the active war for convenience
- Updated automatically when `--war` flag is used

## Architecture

**Stateless Worker + Shared Store:**
- Each CLI invocation is independent and doesn't hold state in memory
- All war data persists in SQLite (`resources/war.db`)
- Multiple wars can coexist without interference
- Race numbering resets per war (each war starts at race #1)
- Standings accumulate within each war independently

## Examples

### Scenario: Processing multiple wars from a livestream

```bash
# Start War 1 (first war)
python -m lakituai --war "War 1: RK vs ne (2026-07-09)" screenshot_race1.jpg

# Continue War 1 with more races
python -m lakituai screenshot_race2.jpg
python -m lakituai screenshot_race3.jpg

# Switch to War 2 (different teams)
python -m lakituai --war "War 2: β vs Falcons (2026-07-09)" screenshot_race1.jpg

# Continue War 2
python -m lakituai screenshot_race2.jpg

# Check standings at any time
python -m lakituai --list-wars

# View current War 1 standings (switch back first)
python -m lakituai --war "War 1: RK vs ne (2026-07-09)" resources/screenshots/dummy.jpg
```

## Future Enhancements

- [ ] UI dashboard showing all wars with detailed standings
- [ ] Export war to CSV/PDF
- [ ] Rename war without data loss
- [ ] Archive/compress old wars
- [ ] Integration with chat to query standings across wars
