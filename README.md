# Claude Timer til Home Assistant

Home Assistant-udgaven af [ClaudeTimer](https://github.com/TimeWinder-dk/ClaudeTimer).
Den viser Claude-forbrug for alle aktive grænser (5-timers session, ugen og
model-afgrænsede uger som Fable) med nedtælling, nulstillingstidspunkt og prognose,
både som kort og som målere.

Grænserne bygges dynamisk ud fra API'ets `limits`-liste, ligesom i Windows-appen,
så nye grænser dukker op uden opdatering.

## Sensorer

For hver grænse (`<g>` er `session`, `weekly`, `weekly_fable`, …):

| Entitet | Indhold |
|---|---|
| `sensor.claude_timer_<g>_usage` | Forbrug i %. Attributter: `level` (good/warning/critical ved 50/80 %), `resets_at`, `forecast_percent`, `hits_limit_at`, `over_pace`, `elapsed_percent`, `model` … |
| `sensor.claude_timer_<g>_reset` | Nulstillingstidspunkt (tidsstempel; HA viser det som en levende nedtælling) |
| `sensor.claude_timer_<g>_forecast` | Forventet forbrug ved nulstilling, hvis tempoet holder |
| `binary_sensor.claude_timer_<g>_over_pace` | Til, hvis grænsen rammes før nulstilling |

Derudover `sensor.claude_timer_extra_usage` (betalt ekstraforbrug, hvis kontoen har det)
og `sensor.claude_timer_last_fetched` (diagnostik, inkl. evt. rate-limit-spærring).

Prognosen er samme beregning som i Windows-appen: lineær fremskrivning ud fra den tid,
der er gået af vinduet. Der vises ingen prognose i de første 5 % af vinduet (mindst
10 min), eller når forbruget er under 1 %.

Entity-id'erne er sprog-uafhængige, mens navnene er oversat (dansk/engelsk). Ved flere
konti får den næste konto endelsen `_2`.

## Visninger

[`dashboards/claude_timer.yaml`](dashboards/claude_timer.yaml) indeholder to visninger:

- **Kort** – som kortene i Windows-appen: forbrug, nedtælling, lokalt
  nulstillingstidspunkt og prognose for alle grænser (finder selv nye grænser),
  plus en historikgraf.
- **Målere** – gauge for forbrug og prognose per grænse med de samme farvegrænser
  (grøn < 50 %, gul < 80 %, rød), nedtælling og "over tempo".

Indsæt: Indstillinger → Dashboards → Tilføj dashboard → ⋮ → Rediger dashboard → ⋮ →
Rå konfigurationseditor.

## Notifikationer

To blueprints i [`blueprints/automation/claude_timer/`](blueprints/automation/claude_timer/):

- `usage_threshold.yaml` – besked når en grænse passerer fx 80 %, med nedtælling og prognose
- `window_reset.yaml` – besked når et vindue nulstilles

Importér dem via Indstillinger → Automatiseringer → Blueprints → Importér, med
URL'en til filen på GitHub.

## Installation

**HACS:** Tilføj repoet som brugerdefineret repository (kategori *Integration*),
installér *Claude Timer* og genstart Home Assistant.

**Manuelt:** Kopiér `custom_components/claude_timer/` til HA's `custom_components/`
og genstart.

Tilføj derefter integrationen under Indstillinger → Enheder og tjenester →
Tilføj integration → *Claude Timer*.

## Login og token-fornyelse

Windows-appen låner Claude Codes token, men det kan Home Assistant ikke (den kører på
en anden maskine). Integrationen logger derfor ind selv med OAuth + PKCE: Du åbner et
link, godkender og indsætter den viste kode (`kode#state`) eller hele sidens URL.

Home Assistant får sit **eget** refresh-token. Det er vigtigt, fordi refresh-tokens
roterer: Hvis to klienter fornyede det samme token, ville de logge hinanden ud.

Fornyelsen er bygget til at kræve så få manuelle logins som muligt:

- Adgangstokenet fornyes 5 minutter før udløb, under en lås, så det roterende
  refresh-token aldrig bruges to gange samtidig.
- Det nye token-sæt gemmes, før det tages i brug.
- Et 401 fra API'et udløser én fornyelse og ét nyt forsøg, før der bedes om nyt login.
- Kun hvis token-endpointet afviser tilladelsen (400/401/403, `invalid_grant`), beder
  HA om nyt login (*reauth*). 429, 5xx og netværksfejl er midlertidige: tokens bevares,
  og der prøves igen ved næste opdatering.
- Ved 429 fra usage-API'et holdes der pause (`Retry-After`, ellers 30 min), da gentagne
  kald kan forlænge en spærring til mange timer.
- Lige efter en nulstilling hentes data igen (30 s efter), så det nye vindue vises hurtigt.

Integrationen beder kun om scopet `user:profile`.

> **Bemærk:** Login bruger Claude Codes offentlige OAuth-klient-id, ligesom andre
> uofficielle værktøjer. Det er ikke et officielt Anthropic-API og kan ændre sig eller
> stoppe uden varsel. Brug det til personligt forbrug.

## Udvikling

```powershell
python -m unittest discover -s tests -v
```

Testene dækker parsing, prognose og token-håndtering (fornyelse, rotation, samtidighed,
401-retry og fejlklassifikation) uden at kræve Home Assistant. CI kører desuden
`hassfest` og HACS-validering.

`translations/*.json`, `strings.json` og `icons.json` er genereret. Ret dem samlet,
så nøglerne stemmer overens.
