/**
 * app.js — Alpine.js converterApp data function
 *
 * Requires: uploader.js (must be loaded before this file)
 * Framework: Alpine.js v3.14.1
 */

/**
 * File size limit constants.
 * Matches backend validation in app.py.
 */
var MAX_FILES = 20;
var MAX_FILE_BYTES = 50 * 1024 * 1024;   // 50 MB per file
var MAX_TOTAL_BYTES = 200 * 1024 * 1024; // 200 MB total
var POLL_INTERVAL_MS = 500;
var FORMAT_SOURCE_MAP = {
  'pdf':  'pdf',
  'docx': 'docx',
  'doc':  'docx',
  'pptx': 'pptx',
  'ppt':  'pptx',
  'html': 'html',
  'htm':  'html',
  'md':   'md',
  'txt':  'txt',
  'png':  'image',
  'jpg':  'image',
  'jpeg': 'image',
  'gif':  'image',
  'bmp':  'image',
  'webp': 'image',
  'tiff': 'image',
  'tif':  'image'
};

/**
 * Return the source format key for a given filename.
 * Returns null if the extension is not recognised.
 *
 * @param {string} filename
 * @returns {string|null}
 */
function detectSourceFormat(filename) {
  var ext = filename.split('.').pop().toLowerCase();
  return FORMAT_SOURCE_MAP[ext] || null;
}

/**
 * Format a byte count as a human-readable string.
 *
 * @param {number} bytes
 * @returns {string}
 */
function formatBytes(bytes) {
  if (bytes === 0) return '0 B';
  var units = ['B', 'KB', 'MB', 'GB'];
  var i = Math.floor(Math.log(bytes) / Math.log(1024));
  return (bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1) + ' ' + units[i];
}

/**
 * Main Alpine.js component data function.
 * Bound to the root element via x-data="converterApp()".
 *
 * @returns {object} Alpine.js reactive data + methods
 */
function converterApp() {
  return {
    /* ── Dark mode ── */
    darkMode: localStorage.getItem('darkMode') !== 'false',

    /* ── UI state ── */
    // 'idle' | 'uploading' | 'processing' | 'completed' | 'partial' | 'failed'
    phase: 'idle',
    isDragOver: false,
    showMatrix: false,

    /* ── File list ── */
    files: [],           // { file: File, sourceFormat: string|null, error: string|null }
    rejectedFiles: [],   // { name: string, reason: string }

    /* ── Format data ── */
    formatsData: null,        // raw API response { formats, matrix }
    availableTargets: [],     // string[] — target formats valid for current selection
    selectedTarget: '',

    /* ── Upload / job progress ── */
    uploadPercent: 0,
    jobId: null,
    jobProgress: 0,
    jobFiles: [],        // per-file results from /api/status
    pollTimer: null,
    _pollErrorCount: 0,  // consecutive poll failures; stops polling at MAX_POLL_ERRORS

    /* ── Result ── */
    downloadUrl: '',
    errorMessage: '',

    /* ────────────────────────────────────────────────────
       Lifecycle
    ──────────────────────────────────────────────────── */

    /**
     * Called by Alpine when the component is initialised (x-init).
     * Applies dark mode, fetches formats, registers keyboard shortcuts.
     */
    init() {
      this.applyDarkMode();
      this.fetchFormats();
      this.registerKeyboardShortcuts();
    },

    /* ────────────────────────────────────────────────────
       Dark mode
    ──────────────────────────────────────────────────── */

    /** Apply or remove the .dark class on <html> and persist the preference. */
    applyDarkMode() {
      if (this.darkMode) {
        document.documentElement.classList.add('dark');
      } else {
        document.documentElement.classList.remove('dark');
      }
      localStorage.setItem('darkMode', this.darkMode ? 'true' : 'false');
    },

    /** Toggle dark mode and persist. */
    toggleDarkMode() {
      this.darkMode = !this.darkMode;
      this.applyDarkMode();
    },

    /* ────────────────────────────────────────────────────
       Format API
    ──────────────────────────────────────────────────── */

    /** Fetch supported formats and conversion matrix from backend. */
    fetchFormats() {
      var self = this;
      fetch('/api/formats')
        .then(function (res) {
          if (!res.ok) throw new Error('HTTP ' + res.status);
          return res.json();
        })
        .then(function (data) {
          self.formatsData = data;
          self.computeAvailableTargets();
        })
        .catch(function (err) {
          console.warn('[converterApp] Could not load formats:', err.message);
          // Non-fatal: UI still works, target selector will be empty until resolved
        });
    },

    /**
     * Compute the intersection of target formats available for ALL currently
     * selected source formats. Updates availableTargets and resets selectedTarget
     * if it is no longer available.
     */
    computeAvailableTargets() {
      if (!this.formatsData || this.files.length === 0) {
        this.availableTargets = [];
        this.selectedTarget = '';
        return;
      }

      var matrix = this.formatsData.matrix;
      var sources = new Set();

      this.files.forEach(function (item) {
        if (item.sourceFormat) {
          sources.add(item.sourceFormat);
        }
      });

      if (sources.size === 0) {
        this.availableTargets = [];
        this.selectedTarget = '';
        return;
      }

      var allTargets = Object.keys(matrix[Array.from(sources)[0]] || {});
      var self = this;

      var validTargets = allTargets.filter(function (fmt) {
        return Array.from(sources).every(function (src) {
          return matrix[src] && matrix[src][fmt];
        });
      });

      this.availableTargets = validTargets;

      if (validTargets.length > 0 && !validTargets.includes(this.selectedTarget)) {
        this.selectedTarget = validTargets[0];
      } else if (validTargets.length === 0) {
        this.selectedTarget = '';
      }
    },

    /* ────────────────────────────────────────────────────
       File handling
    ──────────────────────────────────────────────────── */

    /**
     * Process a FileList or File[] from drop or file input, validate each file,
     * and add valid ones to this.files.
     *
     * @param {FileList|File[]} incoming
     */
    addFiles(incoming) {
      var self = this;
      this.rejectedFiles = [];
      var candidates = Array.from(incoming);

      candidates.forEach(function (file) {
        // Duplicate check
        var isDuplicate = self.files.some(function (item) {
          return item.file.name === file.name && item.file.size === file.size;
        });
        if (isDuplicate) {
          self.rejectedFiles.push({ name: file.name, reason: '已加入（重複）' });
          return;
        }

        // File count limit
        if (self.files.length >= MAX_FILES) {
          self.rejectedFiles.push({ name: file.name, reason: '已達 ' + MAX_FILES + ' 個檔案上限' });
          return;
        }

        // Per-file size limit
        if (file.size > MAX_FILE_BYTES) {
          self.rejectedFiles.push({ name: file.name, reason: '超過單檔 50 MB 限制' });
          return;
        }

        // Total size limit
        var currentTotal = self.files.reduce(function (sum, item) {
          return sum + item.file.size;
        }, 0);
        if (currentTotal + file.size > MAX_TOTAL_BYTES) {
          self.rejectedFiles.push({ name: file.name, reason: '加入後將超過總計 200 MB 限制' });
          return;
        }

        var sourceFormat = detectSourceFormat(file.name);
        if (!sourceFormat) {
          // 明確拒絕不支援的格式，不加入清單
          self.rejectedFiles.push({ name: file.name, reason: '不支援的格式' });
          return;
        }
        self.files.push({
          file: file,
          sourceFormat: sourceFormat,
          error: null
        });
      });

      this.computeAvailableTargets();

      // Auto-clear rejection notice after 5 s
      if (this.rejectedFiles.length > 0) {
        setTimeout(function () {
          self.rejectedFiles = [];
        }, 5000);
      }
    },

    /**
     * Remove one file by index and recompute available targets.
     *
     * @param {number} index
     */
    removeFile(index) {
      this.files.splice(index, 1);
      this.computeAvailableTargets();
    },

    /* ── Drag-and-drop handlers ── */

    handleDragEnter(event) {
      event.preventDefault();
      this.isDragOver = true;
    },

    handleDragOver(event) {
      event.preventDefault();
      this.isDragOver = true;
    },

    handleDragLeave(event) {
      event.preventDefault();
      // Only clear when leaving the dropzone element itself, not a child
      if (!event.currentTarget.contains(event.relatedTarget)) {
        this.isDragOver = false;
      }
    },

    handleDrop(event) {
      event.preventDefault();
      this.isDragOver = false;
      if (event.dataTransfer && event.dataTransfer.files.length > 0) {
        this.addFiles(event.dataTransfer.files);
      }
    },

    /** Open the hidden file input dialog. */
    openFilePicker() {
      var input = this.$refs.fileInput;
      if (input) {
        input.value = '';
        input.click();
      }
    },

    /** Handle change event from the hidden file input. */
    handleFileInputChange(event) {
      if (event.target.files && event.target.files.length > 0) {
        this.addFiles(event.target.files);
      }
    },

    /* ────────────────────────────────────────────────────
       Computed helpers (used in x-bind / x-text)
    ──────────────────────────────────────────────────── */

    /** True when all files have a recognised source format. */
    get allFormatsRecognised() {
      return this.files.length > 0 && this.files.every(function (item) {
        return item.sourceFormat !== null;
      });
    },

    /** True when a conversion can be started. */
    get canConvert() {
      return this.files.length > 0 &&
        this.allFormatsRecognised &&
        this.selectedTarget !== '' &&
        (this.phase === 'idle');
    },

    /** Total size of all queued files as a formatted string. */
    get totalSizeLabel() {
      var total = this.files.reduce(function (sum, item) {
        return sum + item.file.size;
      }, 0);
      return formatBytes(total);
    },

    /** DropZone CSS classes depending on state. */
    get dropzoneClasses() {
      var base = 'dropzone-base';
      if (this.files.length > 0) return base + ' dropzone-compact';
      if (this.isDragOver) return base + ' dropzone-dragover';
      return base + ' dropzone-idle';
    },

    /** Source format display label. */
    formatLabel(key) {
      var labels = {
        pdf: 'PDF', docx: 'Word', pptx: 'PowerPoint',
        html: 'HTML', md: 'Markdown', txt: 'Text', image: '圖片'
      };
      return labels[key] || key.toUpperCase();
    },

    /* ────────────────────────────────────────────────────
       Conversion — start
    ──────────────────────────────────────────────────── */

    /** Start the upload + conversion pipeline. */
    startConversion() {
      if (!this.canConvert) return;

      var self = this;
      var rawFiles = this.files.map(function (item) { return item.file; });

      this.phase = 'uploading';
      this.uploadPercent = 0;
      this.errorMessage = '';
      this._pollErrorCount = 0;  // reset before each new conversion attempt

      uploadFiles(rawFiles, this.selectedTarget, function (percent) {
        self.uploadPercent = percent;
      })
        .then(function (data) {
          self.jobId = data.job_id;
          self.phase = 'processing';
          self.jobProgress = 0;
          self.startPolling();
        })
        .catch(function (err) {
          self.phase = 'failed';
          self.errorMessage = err.message || '上傳失敗，請稍後再試';
        });
    },

    /* ────────────────────────────────────────────────────
       Polling
    ──────────────────────────────────────────────────── */

    /** Begin polling /api/status/<job_id> every POLL_INTERVAL_MS. */
    startPolling() {
      var self = this;
      self.pollTimer = setInterval(function () {
        self.pollStatus();
      }, POLL_INTERVAL_MS);
    },

    /** Stop the polling timer. */
    stopPolling() {
      if (this.pollTimer) {
        clearInterval(this.pollTimer);
        this.pollTimer = null;
      }
    },

    /** Fetch the current job status and update state accordingly. */
    pollStatus() {
      if (!this.jobId) {
        this.stopPolling();
        return;
      }

      var self = this;
      fetch('/api/status/' + self.jobId)
        .then(function (res) {
          if (!res.ok) throw new Error('HTTP ' + res.status);
          return res.json();
        })
        .then(function (data) {
          self._pollErrorCount = 0;  // reset on successful response
          self.jobProgress = data.progress || 0;
          self.jobFiles = data.files || [];

          var terminal = ['completed', 'partial', 'failed', 'delivered'];
          if (terminal.includes(data.status)) {
            self.stopPolling();
            self.phase = data.status === 'delivered' ? 'completed' : data.status;
            if (data.download_url) {
              self.downloadUrl = data.download_url;
            }
            if (data.status === 'failed') {
              self.errorMessage = '轉換失敗，請確認檔案格式是否正確';
            }
          }
        })
        .catch(function (err) {
          self._pollErrorCount++;
          console.warn('[converterApp] Poll error (' + self._pollErrorCount + '):', err.message);
          if (self._pollErrorCount >= 5) {
            self.stopPolling();
            self.phase = 'failed';
            self.errorMessage = '連線中斷，請重新整理頁面後再試';
          }
        });
    },

    /* ────────────────────────────────────────────────────
       Download
    ──────────────────────────────────────────────────── */

    /** Trigger download of the converted file(s). */
    downloadResult() {
      if (!this.downloadUrl) return;
      var a = document.createElement('a');
      a.href = this.downloadUrl;
      a.download = '';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    },

    /* ────────────────────────────────────────────────────
       Reset
    ──────────────────────────────────────────────────── */

    /** Reset the entire UI back to idle state. */
    reset() {
      this.stopPolling();
      this.phase = 'idle';
      this.files = [];
      this.rejectedFiles = [];
      this.selectedTarget = '';
      this.availableTargets = [];
      this.uploadPercent = 0;
      this.jobId = null;
      this.jobProgress = 0;
      this.jobFiles = [];
      this.downloadUrl = '';
      this.errorMessage = '';
      this.isDragOver = false;
      this._pollErrorCount = 0;
      this.computeAvailableTargets();
    },

    /* ────────────────────────────────────────────────────
       Keyboard shortcuts
    ──────────────────────────────────────────────────── */

    /** Register global keyboard shortcuts. */
    registerKeyboardShortcuts() {
      var self = this;
      document.addEventListener('keydown', function (event) {
        // Ctrl+O — open file picker
        if (event.ctrlKey && event.key === 'o') {
          event.preventDefault();
          if (self.phase === 'idle') {
            self.openFilePicker();
          }
          return;
        }
        // Escape — reset to idle
        if (event.key === 'Escape' && self.phase === 'idle') {
          self.reset();
          return;
        }
      });
    },

    /* ────────────────────────────────────────────────────
       Matrix panel
    ──────────────────────────────────────────────────── */

    /** Toggle the format compatibility matrix panel. */
    toggleMatrix() {
      this.showMatrix = !this.showMatrix;
    },

    /**
     * Return the fidelity CSS class for a source→target cell.
     *
     * @param {string} src
     * @param {string} tgt
     * @returns {string}
     */
    fidelityClass(src, tgt) {
      if (!this.formatsData) return 'fidelity-none';
      var matrix = this.formatsData.matrix;
      if (!matrix[src] || !matrix[src][tgt]) return 'fidelity-none';
      var value = matrix[src][tgt];
      if (value === true || value === 'high') return 'fidelity-high';
      if (value === 'medium') return 'fidelity-medium';
      if (value === 'low') return 'fidelity-low';
      return 'fidelity-none';
    },

    /**
     * Return the fidelity label text for a cell.
     *
     * @param {string} src
     * @param {string} tgt
     * @returns {string}
     */
    fidelityLabel(src, tgt) {
      if (!this.formatsData) return '—';
      var matrix = this.formatsData.matrix;
      if (!matrix[src] || !matrix[src][tgt]) return '—';
      var value = matrix[src][tgt];
      if (value === true || value === 'high') return '高';
      if (value === 'medium') return '中';
      if (value === 'low') return '低';
      return '—';
    }
  };
}
