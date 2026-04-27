# HAVE FVCKED — Audio Tools

Strona webowa z funkcjami bota Discord:  
`/bpm` · `/key` · `/split` (Vocal / Bass / Drums / Melody)

---

## Stack

| Warstwa | Technologia |
|---------|------------|
| Frontend | HTML + CSS + vanilla JS (nginx) |
| Backend | Python + Flask |
| Pobieranie | yt-dlp |
| Analiza BPM/Key | librosa |
| Stem separation | demucs (htdemucs model) |
| Konteneryzacja | Docker + Docker Compose |

---

## Wymagania

- Docker + Docker Compose  
- Minimum **4 GB RAM** (demucs jest wymagający)
- Minimum **10 GB** wolnego miejsca  
- GPU opcjonalnie (demucs na CPU działa, ale wolniej ~5-15 min/utwór)

---

## Uruchomienie

### 1. Sklonuj / rozpakuj projekt

```bash
git clone <twoje-repo> havefvcked
cd havefvcked
```

### 2. Uruchom Docker Compose

```bash
docker-compose up --build
```

Pierwsze uruchomienie pobierze model demucs (~300 MB) — tylko raz.

### 3. Otwórz w przeglądarce

```
http://localhost
```

---

## Użycie

1. Wklej link YouTube do pola
2. Kliknij **WCZYTAJ** — zobaczysz tytuł i okładkę
3. Wybierz funkcję:
   - **ANALIZUJ BPM** — tempo w sekundach
   - **ANALIZUJ TONACJĘ** — np. `F# minor`
   - **ROZDZIEL UTWÓR** — pobierz 4 pliki .wav

---

## Hosting na VPS (Hetzner, DigitalOcean, itp.)

```bash
# Na serwerze (Ubuntu 22.04):
apt update && apt install -y docker.io docker-compose-plugin
git clone <repo> havefvcked && cd havefvcked
docker compose up -d --build

# Sprawdź logi:
docker compose logs -f backend
```

Otwórz port 80 w firewallu serwera.

---

## Hosting z domeną (+ SSL przez Cloudflare)

1. Ustaw domenę → IP serwera w DNS Cloudflare  
2. Włącz Proxy (pomarańczowa chmurka) → SSL/TLS → Full  
3. Strona działa na `https://twoja-domena.com`

---

## Konfiguracja GPU (opcjonalnie — znacznie szybszy split)

W `backend/Dockerfile` zamień bazowy obraz:

```dockerfile
FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04
```

I dodaj do `docker-compose.yml` w sekcji `backend`:

```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: 1
          capabilities: [gpu]
```

---

## Struktura projektu

```
havefvcked/
├── backend/
│   ├── app.py              # Flask API
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── index.html          # Cały frontend (1 plik)
│   └── Dockerfile
├── nginx/
│   └── default.conf        # Reverse proxy
├── docker-compose.yml
└── README.md
```

---

## API Endpoints

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `POST /api/info` | POST | Szybki podgląd tytułu/okładki |
| `POST /api/analyze` | POST | Start job BPM + Key |
| `POST /api/split` | POST | Start job stem separation |
| `GET /api/job/:id` | GET | Status job (polling) |
| `GET /api/download/:id/:stem` | GET | Pobierz plik .wav |
| `GET /api/health` | GET | Health check |

---

## Czas przetwarzania (orientacyjny)

| Operacja | CPU | GPU |
|----------|-----|-----|
| /bpm | ~30s | ~10s |
| /key | ~30s | ~10s |
| /split (4 min utwór) | 5-15 min | 1-2 min |

---

## Znane ograniczenia

- YouTube może blokować pobieranie przy dużym ruchu (aktualizuj yt-dlp: `pip install -U yt-dlp`)
- Pliki stem są automatycznie usuwane po **1 godzinie**
- Nie obsługuje live streamów YouTube

---

## Aktualizacja yt-dlp (jeśli YT blokuje)

```bash
docker-compose exec backend pip install -U yt-dlp
docker-compose restart backend
```
