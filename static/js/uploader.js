/**
 * uploader.js — XHR multipart file upload with progress tracking
 *
 * Standalone module with no external dependencies.
 * Called by converterApp() in app.js.
 */

/**
 * Upload files to /api/convert via XHR and report progress.
 *
 * @param {File[]} files          Array of File objects to upload
 * @param {string} targetFormat   Target format key (e.g. "pdf", "docx")
 * @param {function} onProgress   Callback(percent: 0-100) called during upload
 * @returns {Promise<{job_id: string, file_count: number, queued_at: string, estimated_duration_sec: number}>}
 * @throws {Error} If the server returns non-2xx or network fails
 */
function uploadFiles(files, targetFormat, onProgress) {
  return new Promise(function (resolve, reject) {
    if (!files || files.length === 0) {
      reject(new Error('No files provided to upload'));
      return;
    }

    if (!targetFormat) {
      reject(new Error('Target format must be specified'));
      return;
    }

    var xhr = new XMLHttpRequest();
    var formData = new FormData();

    for (var i = 0; i < files.length; i++) {
      formData.append('files', files[i]);
    }
    formData.append('target_format', targetFormat);

    xhr.upload.addEventListener('progress', function (event) {
      if (event.lengthComputable && typeof onProgress === 'function') {
        var percent = Math.round((event.loaded / event.total) * 100);
        onProgress(Math.min(percent, 100));
      }
    });

    xhr.addEventListener('load', function () {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          var data = JSON.parse(xhr.responseText);
          resolve(data);
        } catch (parseError) {
          reject(new Error('Server returned invalid JSON: ' + xhr.responseText.substring(0, 200)));
        }
      } else {
        var errorMessage = 'Upload failed with HTTP ' + xhr.status;
        try {
          var errorData = JSON.parse(xhr.responseText);
          if (errorData.error) {
            errorMessage = errorData.error;
          } else if (errorData.message) {
            errorMessage = errorData.message;
          }
        } catch (ignored) {
          // responseText is not JSON; use generic message
        }
        reject(new Error(errorMessage));
      }
    });

    xhr.addEventListener('error', function () {
      reject(new Error('Network error during upload — please check your connection'));
    });

    xhr.addEventListener('timeout', function () {
      reject(new Error('Upload timed out — file may be too large or connection is slow'));
    });

    xhr.addEventListener('abort', function () {
      reject(new Error('Upload was aborted'));
    });

    xhr.timeout = 300000; // 5-minute timeout for large batches
    xhr.open('POST', '/api/convert');
    xhr.send(formData);
  });
}
