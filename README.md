# Study AI

Study AI is een lokale studie-app voor Windows. Je plakt je eigen leerstof, laat een extern AI-model studiemateriaal maken met een automatisch gegenereerde prompt, en importeert de teruggegeven JSON veilig in de app. Er is geen AI-API of account nodig.

## Installatie en starten

Open PowerShell in deze map:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

De browser opent op http://127.0.0.1:8000. Stoppen kan met `Ctrl+C`. Met `.\start.ps1` worden de omgeving en afhankelijkheden automatisch klaargezet.

## Workflow

Maak een vak en deck, plak de leerstof in het deck, open AI Studio en genereer een prompt. Kopieer die prompt naar ChatGPT, Gemini, Claude, Ollama of een ander model. Plak uitsluitend de ontvangen JSON in AI Studio, controleer de preview en bevestig de import. Flashcards, quizzen, oefentoetsen, open vragen en begrippen worden daarna lokaal opgeslagen.

## Opslag en export

Alle gegevens staan lokaal in `data/studyai.sqlite3`. Gebruik Instellingen om je volledige workspace als JSON te exporteren. De app bevat daarnaast een duidelijke optie om voorbeelddata te laden.

## JSON-formaat

Het AI-formaat gebruikt `format: "study-ai"` en `version: 1`, met `metadata`, `flashcards`, `quizzes`, `tests`, `questions`, `summary` en `key_terms`. AI Studio zet het exacte schema in iedere gegenereerde prompt.

## Problemen oplossen

Controleer of Python 3.10 of nieuwer is geïnstalleerd. Als PowerShell scripts blokkeert, voer eenmalig `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` uit. Verwijder nooit de database als je gegevens wilt behouden; exporteer eerst via Instellingen.
