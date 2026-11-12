# Technology downgrade monitor

Dieser Python-Scanner sucht S&P-500-Technologieaktien nach einem echten Rating-Downgrade, einem Kursrueckgang von mindestens 3% und einem bestaetigten taeglichen SMA5-Cross innerhalb der naechsten fuenf Sitzungen. Der geplante Einstieg ist der folgende regulaere US-Open. 20 Sitzungen sind der geplante spaetere Haltezeitraum, kein Wartezeitraum fuer die Benachrichtigung. 5x ist das ausgewaehlte Papierszenario; es werden keine Orders erteilt.

## Meldungen aufs Android-Handy

Telegram und ntfy werden unterstuetzt. Sind `TELEGRAM_BOT_TOKEN` und `TELEGRAM_CHAT_ID` als Actions-Secrets eingerichtet, verwendet die Cloud ausschliesslich Telegram. Solange die Telegram-Chat-ID noch fehlt, bleibt der bisherige ntfy-Kanal aktiv. Der Versand bestaetigt nur die Annahme durch den Dienst; eine Benachrichtigung bei gesperrtem Handy muss separat getestet werden.

**Neue technische Einstiegssignale werden ausdruecklich als UNGEPRUEFT / Nachrichtenpruefung ausstehend gemeldet.** Der Empfaenger prueft die verlinkten Nachrichten selbst. Die reine zeitliche Naehe eines Downgrades beweist keine Ursache und keinen Analystenfehler. Diese Cloud-Version nutzt keine kostenpflichtige KI-Nachrichtenanalyse. Wenn eine vollstaendige, gueltige manuelle Bewertung vorhanden ist, kann sie eine bestaetigte Meldung erzeugen.

Bereits ausgeschlossene konkurrierende Unternehmensmeldungen sowie starke Markt-/Sektortage erzeugen keine Kandidatenmeldungen. Die mechanischen Grenzen sind absolute SPY-Bewegungen ab 2% bzw. XLK ab 3%. Unvollstaendige Tageskurse werden nicht fuer einen Cross verwendet. Das Ereignisdatum ohne gepruefte Uhrzeit verwendet konservativ die erste volle US-Sitzung nach dem Rating-Datum; eine belegte Uhrzeit kann die Reaktionssitzung korrigieren.

## Kostenrahmen

Das Workflow-Template ist auf **ein oeffentliches Repository und den kostenlosen Standard-Runner `ubuntu-latest`** begrenzt. Bei privater Sichtbarkeit startet der Job nicht. Es gibt keinen bezahlten Runner, keine bezahlte Daten- oder KI-API, keine Codespaces, keine Paket-/Artifact-Uploads und keinen GitHub-Actions-Cache. Die [Telegram Bot API](https://core.telegram.org/bots) wird fuer die wenigen persoenlichen Meldungen kostenlos genutzt; kostenpflichtige Broadcasts sind nicht aktiviert. Auch `ntfy.sh` wird ohne Bezahlabo genutzt. Die Angaben folgen den aktuellen [GitHub-Regeln fuer oeffentliche Standard-Runner](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job).

## Einrichtung

1. Diese bereinigten Dateien in ein eigenes oeffentliches Repository uebernehmen. Keine lokalen Kontodaten, Forschungsarchive, QR-Codes oder ntfy-Themennamen hochladen.
2. Fuer Telegram den Bot-Token ausschliesslich als verschluesseltes Actions-Secret **TELEGRAM_BOT_TOKEN** speichern. Dem eigenen Bot einen zufaelligen einmaligen Code im Format `verbinden-` plus 24 kleine Hexadezimalzeichen senden. Den Workflow einmal mit diesem `pair_code` ausfuehren; er sendet die private Chat-ID nur an den passenden privaten Chat. Die Zahl anschliessend als **TELEGRAM_CHAT_ID** speichern. Kein Token und keine Chat-ID gehoeren in oeffentlichen Code oder Logs. Alternativ den ntfy-Themennamen als **NTFY_TOPIC** speichern.
3. Das Template als `.github/workflows/scanner-cloud.yml` hinzufuegen. Die Zeitplanung erst nach einem erfolgreichen manuellen Cloud-Test aktivieren.
4. Unter Actions den Workflow manuell mit `send_test=true` ausfuehren. Ein klar gekennzeichneter Test muss direkt von GitHub zum Handy gelangen. Ein erfolgreicher lokaler Test ersetzt diesen Cloud-Test nicht.

Die Zeitplanung verwendet ausdruecklich UTC: montags bis freitags alle 15 Minuten zwischen 06:13 und 23:58 UTC, jeweils um :13, :28, :43 und :58. Berlin liegt im Winter eine und im Sommer zwei Stunden vor UTC. Automatische Laeufe sind als `TECH3 scan - schedule` gekennzeichnet, manuelle Laeufe als `TECH3 scan - workflow_dispatch`. Der Scanner ueberspringt NYSE-Nichthandelstage und beruecksichtigt regulaere sowie verkuerzte Sitzungen. Tages-SMA5 benoetigt abgeschlossene Schlusskurse, keine Echtzeit-Ticks. Ein erfolgreicher manueller Lauf bestaetigt nicht die automatische Zeitplanung; deren Ausfuehrung muss anhand eines echten `schedule`-Ereignisses geprueft werden.

Geplante GitHub-Jobs und die kostenlosen Datenquellen koennen verzoegert sein oder ausfallen. Das ist kein zeitgarantierter Boersendienst. Nasdaq kann Cloud-IP-Adressen sperren; deshalb wird der echte Serverlauf vor Aktivierung getestet. Quellen: Nasdaq-Tageshistorien, The-Fly-Ratingtabellen via Daily Trade Alert und datierte S&P-500-Snapshots aus GitHub.

## Zustand und Datenschutz

`monitor-state.json` enthaelt oeffentliche Ereignisbewertungen, zuletzt verarbeitete Marktsitzungen und technische Zustellungs-IDs zur Vermeidung doppelter Meldungen. Es enthaelt weder Telegram-Token und Chat-ID noch das ntfy-Thema, Kontostaende oder Depotpositionen. Die Zugangsdaten werden nur aus Secrets gelesen. Das unerratbare ntfy-Thema ist keine authentifizierte private Mailbox; seinen Namen geheim halten.

Die lokale Codex-Automation soll erst nach erfolgreicher Cloud-Aktivierung umgestellt werden. Nicht unabhaengig beide Systeme mit getrennten Zustellungsregistern betreiben. Der oeffentliche Code ist ein Forschungswerkzeug und keine Aussage, dass die Strategie einen verlaesslichen Vorteil hat.
