# Technology downgrade monitor

Dieser Python-Scanner sucht S&P-500-Technologieaktien nach einem echten Rating-Downgrade, einem Kursrueckgang von mindestens 3% und einem bestaetigten taeglichen SMA5-Cross innerhalb der naechsten fuenf Sitzungen. Der geplante Einstieg ist der folgende regulaere US-Open. 20 Sitzungen sind der geplante spaetere Haltezeitraum, kein Wartezeitraum fuer die Benachrichtigung. 5x ist das ausgewaehlte Papierszenario; es werden keine Orders erteilt.

## Meldungen aufs Android-Handy

**Neue technische Einstiegssignale werden ausdruecklich als UNGEPRUEFT / Nachrichtenpruefung ausstehend gemeldet.** Der Empfaenger prueft die verlinkten Nachrichten selbst. Die reine zeitliche Naehe eines Downgrades beweist keine Ursache und keinen Analystenfehler. Diese Cloud-Version nutzt keine kostenpflichtige KI-Nachrichtenanalyse. Wenn eine vollstaendige, gueltige manuelle Bewertung vorhanden ist, kann sie eine bestaetigte Meldung erzeugen.

Bereits ausgeschlossene konkurrierende Unternehmensmeldungen sowie starke Markt-/Sektortage erzeugen keine Kandidatenmeldungen. Die mechanischen Grenzen sind absolute SPY-Bewegungen ab 2% bzw. XLK ab 3%. Unvollstaendige Tageskurse werden nicht fuer einen Cross verwendet. Das Ereignisdatum ohne gepruefte Uhrzeit verwendet konservativ die erste volle US-Sitzung nach dem Rating-Datum; eine belegte Uhrzeit kann die Reaktionssitzung korrigieren.

## Kostenrahmen

Das Workflow-Template ist auf **ein oeffentliches Repository und den kostenlosen Standard-Runner `ubuntu-latest`** begrenzt. Bei privater Sichtbarkeit startet der Job nicht. Es gibt keinen bezahlten Runner, keine bezahlte Daten- oder KI-API, keine Codespaces, keine Paket-/Artifact-Uploads und keinen GitHub-Actions-Cache. `ntfy.sh` wird ohne Bezahlabo genutzt. Die Angaben folgen den aktuellen [GitHub-Regeln fuer oeffentliche Standard-Runner](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job).

## Einrichtung

1. Diese bereinigten Dateien in ein eigenes oeffentliches Repository uebernehmen. Keine lokalen Kontodaten, Forschungsarchive, QR-Codes oder ntfy-Themennamen hochladen.
2. Den ntfy-Themennamen ausschliesslich als verschluesseltes Actions-Secret **NTFY_TOPIC** speichern.
3. Das Template als `.github/workflows/scanner-cloud.yml` hinzufuegen. Die Zeitplanung erst nach einem erfolgreichen manuellen Cloud-Test aktivieren.
4. Unter Actions den Workflow manuell mit `send_test=true` ausfuehren. Ein klar gekennzeichneter Test muss direkt von GitHub zum Handy gelangen. Ein erfolgreicher lokaler Test ersetzt diesen Cloud-Test nicht.

Die vorbereitete Zeitplanung prueft montags bis freitags alle 15 Minuten in den Stunden 08, 13, 14, 18, 19, 21, 22 und 23 Europe/Berlin, jeweils um :05, :20, :35 und :50. Der Scanner ueberspringt NYSE-Nichthandelstage und beruecksichtigt regulaere sowie verkuerzte Sitzungen. Tages-SMA5 benoetigt abgeschlossene Schlusskurse, keine Echtzeit-Ticks.

Geplante GitHub-Jobs und die kostenlosen Datenquellen koennen verzoegert sein oder ausfallen. Das ist kein zeitgarantierter Boersendienst. Nasdaq kann Cloud-IP-Adressen sperren; deshalb wird der echte Serverlauf vor Aktivierung getestet. Quellen: Nasdaq-Tageshistorien, The-Fly-Ratingtabellen via Daily Trade Alert und datierte S&P-500-Snapshots aus GitHub.

## Zustand und Datenschutz

`monitor-state.json` enthaelt oeffentliche Ereignisbewertungen, zuletzt verarbeitete Marktsitzungen und zufaellige Zustellungs-IDs zur Vermeidung doppelter Meldungen. Es enthaelt weder das ntfy-Thema noch Kontostaende, Depotpositionen oder Zugangsdaten. Der ntfy-Themenname wird nur aus dem Secret gelesen. Das unerratbare ntfy-Thema ist keine authentifizierte private Mailbox; seinen Namen geheim halten.

Die lokale Codex-Automation soll erst nach erfolgreicher Cloud-Aktivierung umgestellt werden. Nicht unabhaengig beide Systeme mit getrennten Zustellungsregistern betreiben. Der oeffentliche Code ist ein Forschungswerkzeug und keine Aussage, dass die Strategie einen verlaesslichen Vorteil hat.
