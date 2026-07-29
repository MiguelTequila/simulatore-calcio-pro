# ⚽ Guida al Simulatore Predittivo Pro

## Cos'è
Uno strumento che stima le probabilità delle partite (1-X-2, Over/Under 2.5, GG/NG,
risultati esatti) con un modello **Dixon-Coles** alimentato da statistiche reali,
**Elo dinamico** e quote di mercato, e che segnala dove il modello vede **valore**
rispetto alle quote dei bookmaker.

## Competizioni coperte
Premier League, Ligue 1, La Liga, Serie A, Primeira Liga, Bundesliga, Eredivisie,
Champions League. I dati arrivano da Football-Data.org (statistiche/calendari,
gratuito su 12 competizioni) e The Odds API (quote, 500 crediti/mese gratuiti).
Europa League e Nations League NON sono nel piano gratuito di Football-Data:
per quelle partite usa la **modalità manuale**.

## Uso quotidiano
1. Apri il sito. Il badge in alto mostra data dell'ultimo aggiornamento e
   **crediti Odds API residui** (es. `🪙 483/500`). I dati si aggiornano da soli
   una volta al giorno (~18:00 ora italiana).
2. Scegli **Competizione** e **Partita**: statistiche, Elo, forma e quote si
   compilano da sole.
3. Leggi la **Predizione**: barra 1-X-2, risultati esatti più probabili,
   Over/Under, GG/NG, distribuzione gol.
4. Guarda la scheda **💎 Valore**: confronta la probabilità del modello con la
   quota migliore trovata. Se il vantaggio ("edge") è ≥ 3%, viene proposta una
   **bet di valore** con la puntata suggerita (½ Kelly, max 5% del bankroll).
   - *Vantaggio = probabilità del modello × quota − 1.* Un +5% significa che,
     SE il modello ha ragione, quella quota è pagata più del giusto.
5. **Salva nel registro** le predizioni che vuoi tracciare; esportale in CSV
   quando vuoi (restano solo nel tuo browser).

## Modalità manuale
Per leghe non coperte (Serie B, Europa League, nazionali, amichevoli):
premi **✏️ Inserisci dati a mano**, metti gol fatti/subiti a partita, forma
(es. `WWDLW`) e, se le hai, le quote. Con le quote il modello si calibra e
calcola anche il valore.

## 📈 Verifica del modello (in fondo alla pagina)
Ogni aggiornamento registra le predizioni e, quando le partite finiscono,
aggancia da solo i risultati reali. La sezione mostra:
- **Partite valutate / in attesa** — dimensione del campione.
- **Brier score** — errore medio delle probabilità (più basso = meglio;
  0.25 equivale a tirare a caso su eventi 50/50).
- **Calibrazione** — per ogni fascia (es. 60-70%): barra blu = probabilità
  media prevista, barra verde = frequenza con cui l'evento è successo davvero.
  Modello onesto ⇒ barre simili.
- **Value bet: P&L e ROI** — come sarebbe andata puntando 1 unità fissa su ogni
  bet di valore segnalata, alla quota registrata.

⚠️ Fidati di questi numeri solo con campione ampio: sotto le ~50 partite
valutate il ROI oscilla per puro caso. E a inizio stagione il modello è più
debole: tratta gli edge come segnali, non come certezze.

## Crediti API: come non sforare
- Il consumo è ~2 crediti per competizione per giorno, **solo** per le
  competizioni con partite nei 45 giorni successivi (le settimane senza
  Champions non consumano nulla).
- Il residuo esatto lo vedi: nel **badge sul sito**, nei **log di GitHub
  Actions** (riga "crediti Odds API rimasti"), o nella dashboard di
  the-odds-api.com col tuo account.
- Se il badge va sotto ~60 diventa rosso: in quel caso salta qualche giorno
  o riduci le competizioni.

## Manutenzione
- Aggiornamento manuale: GitHub → Actions → *Update Football Data* → Run workflow.
- I file di stato (`data/elo_state.json`, `data/predictions_log.json`,
  `data/track_record.json`) si gestiscono da soli: **non cancellarli**, o
  perdi Elo accumulato e storico.

## Limiti onesti
- Le probabilità sono stime: il modello NON conosce infortuni, squalifiche,
  turnover, motivazioni.
- Il mercato dei bookmaker è molto efficiente: la maggior parte degli "edge"
  grandi è un errore del modello, non un regalo del book.
- Gioca solo ciò che puoi permetterti di perdere. Il ½ Kelly col tetto al 5%
  esiste per proteggerti dalla rovina, non per garantire profitto.

## ✏️ Inserire le quote a mano (partite senza quote automatiche)
Se una partita ha statistiche ma **nessuna quota** (competizione fuori finestra,
crediti esauriti, o lega non coperta dall'API delle quote), non serve rifare tutto
in modalità manuale: nella scheda della predizione trovi il riquadro
**"✏️ Quote tue"**.

1. Scrivi le quote del tuo bookmaker (Eurobet, Sisal, quello che usi). Basta
   la tripla 1-X-2 **oppure** Over/Under 2.5; se metti entrambe la calibrazione
   è più precisa.
2. Premi **🎯 Ricalcola con queste quote**: il modello si ricalibra partendo dai
   lambda statistici grezzi e calcola il valore **sulle tue quote reali**.
3. **↩️ Torna al modello puro** annulla e ripristina la predizione statistica.

Funziona anche quando le quote automatiche ci sono già: serve a confrontare il
modello con il prezzo che paghi *tu*, non con la media dei bookmaker europei.

⚠️ Se compare l'avviso arancione **"Vantaggio anomalo"** (edge oltre il 25%),
non puntare: significa che il modello ha troppi pochi dati (tipico a inizio
stagione) e sta sbagliando lui, non il bookmaker.
