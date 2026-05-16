# residential_100 — 100 Residential House Layouts

## Generation Prompt

This dataset was generated with the following instruction given to Claude Code:

> "Crea una nueva carpeta para 20 casas complejas que tenga cuartos con formas no cuadradas, irregulares, pero con formas rectas y puertas intermedias a las habitaciones. Tienen que tener las ventanas al exterior. Deben tener por lo menos una puerta de 2 metros que de al exterior. Y tienen que también tener su mobiliario. Como por ejemplo, cuando hagas los IDs la identificación de los cuartos, estos deben tener su nombre en inglés e incluir los mobiliarios correspondientes. Como por ejemplo, una sala debe incluir sus sillones, mesa, televisión, etcétera. Entonces ejecuta este comando aquí directamente en Claude, sin generar un Python script, en esta nueva carpeta. Asegúrate de poder distinguir todos los elementos en su categoría adecuada y cada 1 de las habitaciones con su categoría adecuada. **HAZ QUE LAS CASAS SEAN MUY DIFERENTES ENTRE SI, CAMBIA EL NUMERO DE HABITACIONES, UBICACION, INTENTA QUE NO TODO SEA CUADRADO, HAZ FORMAS IRREGULARES.**"

The set was then expanded to 100 houses:

> "Agrega 30 más para que sean 100. Elimina las primeras 8 y cámbialas con este nuevo proceso. Cambia el nombre del folder a residential_100."

## How It Works

Houses were generated in two passes:

### Pass 1 — Hand-crafted (houses 009–020)
Claude Code generated these 12 houses directly as JSON files, each manually designed with:
- Non-rectangular outlines (L-shape, Z-shape, T-shape, narrow townhouse)
- L-shaped rooms inside rectangular outlines
- Complex spatial programs (2 master suites, home office, kids zones, garage, laundry)
- Careful area tiling (shoelace formula verified)

### Pass 2 — Parametric generator (houses 001–008 and 021–100)
Script: `team_03/layout/generate_residential.py`  
Seed: `random.seed(20260515)`

8 blueprint functions with parametric dimensions:

| Blueprint | Description | Houses |
|---|---|---|
| `gen_compact` | Studio / 1-bed (80–110m²), 4 rooms | 001, 021–028 |
| `gen_3bed` | 3-bedroom rectangle (120–165m²), 8 rooms | 002–004, 029–043 |
| `gen_4bed` | 4-bedroom rectangle (160–230m²), 9 rooms | 005, 044–056 |
| `gen_townhouse` | Narrow tall (6–8m × 18–24m), 8 rooms | 006, 057–066 |
| `gen_openplan` | Open plan 2-bed (88–126m²), 4 rooms | 007, 067–074 |
| `gen_l_outline` | L-shaped outline 3-bed (128–176m²), 8 rooms | 008, 075–082 |
| `gen_5bed` | Grand 5-bed (200–264m²), 11 rooms | 083–090 |
| `gen_garage` | With garage 3-bed (162–231m²), 8 rooms | 091–100 |

To regenerate:
```bash
cd team_03/layout
python generate_residential.py
```

## Schema

Each file follows the 7-layer layout schema defined in `layout_input/layout_schema.json`:

| Layer | Contents |
|---|---|
| `outline` | Exterior boundary (closed polyline) |
| `rooms` | All habitable spaces with areas |
| `doors` | Interior + exterior doors with `connectsRooms` |
| `windows` | Exterior windows only with `roomId` |
| `furniture` | Type-appropriate furniture per room |
| `mep` | HVAC, electrical panel, water heater |
| `structure` | Load-bearing walls and partitions |

## Design Rules

- Every house has **at least one exterior door ≥ 2m wide**
- Windows are **exterior only** (on the outline boundary)
- All rooms reachable via the door connectivity graph
- Room areas sum to outline area (tiling constraint)
- Room names in **English**
- Furniture appropriate to room type (beds in bedrooms, counters in kitchen, etc.)

## Dataset Statistics

| Property | Range |
|---|---|
| House area | 80 – 264 m² |
| Room count | 4 – 12 |
| Bedrooms | 1 – 5 |
| Bathrooms | 1 – 3 |
| Outline shapes | Rectangle, L-shape, Townhouse |
| Furniture items per house | 10 – 35 |
