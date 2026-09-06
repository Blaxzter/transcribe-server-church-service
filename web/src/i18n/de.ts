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
    back: "Zurück zur Übersicht",
    skipToContent: "Zum Inhalt springen",
  },

  theme: {
    label: "Darstellung",
    light: "Hell",
    dark: "Dunkel",
    system: "System",
  },

  /** Generic verbs and labels; reuse these before inventing a new key. */
  common: {
    cancel: "Abbrechen",
    confirm: "Bestätigen",
    retry: "Erneut versuchen",
    reload: "Seite neu laden",
    search: "Suchen",
    clear: "Eingabe löschen",
    sort: "Sortierung",
    filter: "Filter",
    of: "von",
    dismiss: "Ausblenden",
  },

  units: {
    minuteShort: "Min",
    hourShort: "Std",
    speakers: "Sprecher",
    recordingOne: "Aufnahme",
    recordingMany: "Aufnahmen",
  },

  /** Headings for the age-grouped recordings list. */
  time: {
    today: "Heute",
    yesterday: "Gestern",
    thisWeek: "Diese Woche",
    lastWeek: "Letzte Woche",
    thisMonth: "Dieser Monat",
    earlier: "Früher",
    unknownDate: "Ohne Datum",
  },

  upload: {
    title: "Aufnahme hochladen",
    dropzone: "Datei hierher ziehen",
    dropzoneHint: "oder klicken zum Auswählen",
    dropActive: "Loslassen zum Hochladen",
    formats: "MP3, WAV, M4A, FLAC, OGG, MP4, MOV und weitere",
    remaining: "verbleibend",
    cancel: "Abbrechen",
    retry: "Erneut versuchen",
    failed: "Upload fehlgeschlagen",
    done: "Upload abgeschlossen",
    queued: "Die Verarbeitung startet gleich.",
    resumeHint: "Der Upload wird bei einer Unterbrechung automatisch fortgesetzt.",
    unsupported: "Dieses Dateiformat wird nicht unterstützt.",
  },

  jobs: {
    empty: "Noch keine Aufnahmen vorhanden.",
    emptyHint: "Lade oben eine Aufnahme hoch, um zu beginnen.",
    listTitle: "Aufnahmen",
    duration: "Dauer",
    speakers: "Sprecher",
    created: "Hochgeladen",
    delete: "Löschen",
    deleteTitle: "Aufnahme löschen",
    deleteDescription:
      "Transkript, Zusammenfassung und Audio werden unwiderruflich entfernt.",
    deleteAction: "Endgültig löschen",
    retry: "Neu verarbeiten",
    retryTitle: "Aufnahme neu verarbeiten",
    retryDescription:
      "Die Aufnahme wird erneut durch die Verarbeitung geschickt. Bearbeitungen am Transkript gehen dabei verloren.",
    retryAction: "Neu verarbeiten",
    untitled: "Ohne Titel",
    search: "Aufnahmen durchsuchen…",
    searchEmpty: "Keine Aufnahme gefunden.",
    searchEmptyHint: "Andere Suchbegriffe oder einen anderen Filter versuchen.",
    resetFilters: "Filter zurücksetzen",
    filterAll: "Alle",
    filterDone: "Fertig",
    filterActive: "In Arbeit",
    filterFailed: "Fehlgeschlagen",
    sortNewest: "Neueste zuerst",
    sortOldest: "Älteste zuerst",
    sortTitle: "Nach Titel",
    sortLongest: "Längste zuerst",
    totalDuration: "Gesamtdauer",
    legacy: "Übernommen",
  },

  /** Indexed dynamically by JobStatus — every member of that union needs a key. */
  status: {
    queued: "In Warteschlange",
    running: "Wird verarbeitet",
    done: "Fertig",
    failed: "Fehlgeschlagen",
    canceled: "Abgebrochen",
  },

  /** Indexed dynamically by Stage — every member of that union needs a key. */

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
    notFound: "Aufnahme nicht gefunden.",
    processing: "Die Aufnahme wird verarbeitet. Das dauert bei einem Gottesdienst",
    processingTime: "etwa 10 bis 15 Minuten.",
    failedTitle: "Verarbeitung fehlgeschlagen",
    titlePlaceholder: "Titel der Aufnahme",
    titleLabel: "Titel",
    dateLabel: "Datum des Gottesdienstes",
    saved: "Gespeichert",
    saving: "Wird gespeichert…",
    saveFailed: "Konnte nicht gespeichert werden",
    file: "Datei",
    size: "Größe",
    language: "Sprache",
    finished: "Fertiggestellt",
    segments: "Abschnitte",
  },

  /** Sidebar tabs on the detail page. */
  detail: {
    tabSummary: "Zusammenfassung",
    tabSpeakers: "Sprecher",
    tabExport: "Export",
    tabDetails: "Details",
  },

  player: {
    play: "Abspielen",
    pause: "Pause",
    skipBack: "15 Sekunden zurück",
    skipForward: "15 Sekunden vor",
    speed: "Geschwindigkeit",
    loading: "Wellenform wird geladen…",
    restart: "Von vorn abspielen",
    failed: "Audio konnte nicht geladen werden.",
    playbackFailed: "Wiedergabe konnte nicht gestartet werden.",
  },

  transcript: {
    search: "Im Transkript suchen…",
    noResults: "Keine Treffer.",
    resultCount: "Treffer",
    editHint: "Zum Bearbeiten in einen Absatz klicken.",
    renameSpeaker: "Sprecher umbenennen",
    speakerName: "Name",
    speakerUnknown: "Unbekannt",
    save: "Speichern",
    cancel: "Abbrechen",
    music: "Musik",
    imported:
      "Aus dem alten System übernommen — ohne Sprecher, Musikmarkierungen und Zusammenfassung.",
    segments: "Abschnitte",
    followPlayback: "Wiedergabe folgen",
    jumpTo: "An diese Stelle springen",
    copyAll: "Transkript kopieren",
    edited: "Bearbeitet",
    empty: "Dieses Transkript enthält keinen Text.",
  },

  summary: {
    title: "Zusammenfassung",
    outline: "Gliederung",
    missing: "Für diese Aufnahme wurde keine Zusammenfassung erstellt.",
    copy: "Zusammenfassung kopieren",
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

  /** Short feedback shown in the toast stack. */
  toast: {
    deleted: "Aufnahme gelöscht",
    deleteFailed: "Aufnahme konnte nicht gelöscht werden",
    saveFailed: "Änderung konnte nicht gespeichert werden",
    copied: "In die Zwischenablage kopiert",
    copyFailed: "Kopieren nicht möglich",
    exportStarted: "Export wird vorbereitet",
    retryQueued: "Aufnahme wird neu verarbeitet",
    retryFailed: "Neuverarbeitung konnte nicht gestartet werden",
  },

  errors: {
    loadFailed: "Konnte nicht geladen werden.",
    boundaryTitle: "Die Ansicht konnte nicht dargestellt werden.",
    boundaryHint: "Ein Neuladen der Seite behebt das meistens.",
  },

  a11y: {
    closeDialog: "Dialog schließen",
    loading: "Inhalt wird geladen",
  },
} as const;

export type Messages = typeof de;
