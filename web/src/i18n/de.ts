/**
 * Every user-facing string lives here. Code, identifiers and comments stay in
 * English; the UI is entirely German.
 */
export const de = {
  app: {
    name: "Transkript",
    tagline: "Gottesdienste transkribieren",
  },

  nav: {
    jobs: "Aufnahmen",
    back: "Zurück zur Übersicht",
  },

  upload: {
    title: "Aufnahme hochladen",
    dropzone: "Datei hierher ziehen",
    dropzoneHint: "oder klicken zum Auswählen",
    formats: "MP3, WAV, M4A, FLAC, OGG, MP4, MOV und weitere",
    button: "Datei auswählen",
    uploading: "Wird hochgeladen",
    remaining: "verbleibend",
    cancel: "Abbrechen",
    retry: "Erneut versuchen",
    failed: "Upload fehlgeschlagen",
    resumeHint: "Der Upload wird bei einer Unterbrechung automatisch fortgesetzt.",
    tooLarge: "Die Datei ist zu groß.",
    unsupported: "Dieses Dateiformat wird nicht unterstützt.",
  },

  jobs: {
    empty: "Noch keine Aufnahmen vorhanden.",
    emptyHint: "Lade oben eine Aufnahme hoch, um zu beginnen.",
    listTitle: "Aufnahmen",
    duration: "Dauer",
    speakers: "Sprecher",
    created: "Hochgeladen",
    open: "Öffnen",
    delete: "Löschen",
    deleteConfirm: "Diese Aufnahme mit allen Daten wirklich löschen?",
    retry: "Neu verarbeiten",
    untitled: "Ohne Titel",
  },

  status: {
    queued: "In Warteschlange",
    running: "Wird verarbeitet",
    done: "Fertig",
    failed: "Fehlgeschlagen",
    canceled: "Abgebrochen",
    uploading: "Wird hochgeladen",
  },

  stages: {
    normalize: "Audio wird aufbereitet",
    peaks: "Wellenform wird berechnet",
    music: "Musik wird erkannt",
    vad: "Sprache wird gesucht",
    asr: "Text wird erkannt",
    align: "Zeitstempel werden verfeinert",
    diarize: "Sprecher werden unterschieden",
    merge: "Transkript wird zusammengesetzt",
    summarize: "Zusammenfassung wird erstellt",
  },

  job: {
    processing: "Die Aufnahme wird verarbeitet. Das dauert bei einem Gottesdienst",
    processingTime: "etwa 10 bis 15 Minuten.",
    failedTitle: "Verarbeitung fehlgeschlagen",
    titlePlaceholder: "Titel der Aufnahme",
    datePlaceholder: "Datum",
    saved: "Gespeichert",
    saving: "Wird gespeichert…",
    saveFailed: "Konnte nicht gespeichert werden",
  },

  player: {
    play: "Abspielen",
    pause: "Pause",
    skipBack: "15 Sekunden zurück",
    skipForward: "15 Sekunden vor",
    speed: "Geschwindigkeit",
    loading: "Wellenform wird geladen…",
  },

  transcript: {
    title: "Transkript",
    search: "Im Transkript suchen…",
    noResults: "Keine Treffer.",
    editHint: "Zum Bearbeiten in einen Absatz klicken.",
    renameSpeaker: "Sprecher umbenennen",
    speakerName: "Name",
    save: "Speichern",
    cancel: "Abbrechen",
    music: "Musik",
    segments: "Abschnitte",
    followPlayback: "Wiedergabe folgen",
  },

  summary: {
    title: "Zusammenfassung",
    outline: "Gliederung",
    missing: "Für diese Aufnahme wurde keine Zusammenfassung erstellt.",
  },

  exportMenu: {
    title: "Exportieren",
    docx: "Word-Dokument (.docx)",
    md: "Markdown (.md)",
    txt: "Textdatei (.txt)",
    srt: "Untertitel (.srt)",
    vtt: "Untertitel (.vtt)",
    original: "Originaldatei herunterladen",
  },

  errors: {
    generic: "Etwas ist schiefgelaufen.",
    notFound: "Nicht gefunden.",
    loadFailed: "Konnte nicht geladen werden.",
    retry: "Erneut versuchen",
  },
} as const;

export type Messages = typeof de;
