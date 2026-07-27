# ⚽ Simulatore Predittivo Pro

Modello predittivo calcistico con **Dixon-Coles + Elo dinamico**.
Dati e quote si aggiornano automaticamente ogni 6h via GitHub Actions.

## 🌐 Usa l'app
Dopo aver attivato GitHub Pages, l'app sarà disponibile all'indirizzo:
```
https://TUO_USERNAME.github.io/simulatore-calcio-pro/
```

## 🔧 Setup sviluppo locale
```bash
pip install requests
python src/update_data.py
```

## 📊 Leghe coperte automaticamente
- Premier League (Inghilterra)
- Championship (Inghilterra)
- Serie A (Italia)
- La Liga (Spagna)
- Bundesliga (Germania)
- Ligue 1 (Francia)
- Eredivisie (Olanda)
- Primeira Liga (Portogallo)
- Champions League
- Europa League
- Conference League
- Brasileirão Série A (Brasile)
- Allsvenskan (Svezia)
- Eliteserien (Norvegia)
- Veikkausliiga (Finlandia)

## ⚠️ Limiti
- Il modello descrive il mercato, non lo batte sistematicamente.
- API free tier hanno rate limit.
- Forma e quote sono auto-recuperate ma verificabili/modificabili.
