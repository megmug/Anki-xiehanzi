  function getWriterSize(configuredSize) {
    var configured = parseInt(configuredSize, 10);
    if (!isFinite(configured) || configured <= 0) {
      configured = 400;
    }

    var viewportWidth = 0;
    if (window.visualViewport && window.visualViewport.width) {
      viewportWidth = window.visualViewport.width;
    }
    if (document.documentElement && document.documentElement.clientWidth) {
      viewportWidth = viewportWidth
        ? Math.min(viewportWidth, document.documentElement.clientWidth)
        : document.documentElement.clientWidth;
    }
    if (window.innerWidth) {
      viewportWidth = viewportWidth
        ? Math.min(viewportWidth, window.innerWidth)
        : window.innerWidth;
    }

    var available = Math.floor(viewportWidth - 32);
    if (!isFinite(available) || available <= 0) {
      return configured;
    }
    return Math.max(100, Math.min(configured, available));
  }

  var configuredCharHW = parseInt(WRITE_SETTINGS.grid_size, 10);
  if (!isFinite(configuredCharHW) || configuredCharHW <= 0) {
    configuredCharHW = 400;
  }
  var charHW = getWriterSize(configuredCharHW);
  var charHeight = charHW;
  var charWidth = charHW;
  var configuredStrokeWidth = Number(WRITE_SETTINGS.stroke_width);
  if (!isFinite(configuredStrokeWidth) || configuredStrokeWidth <= 0) {
    configuredStrokeWidth = 64;
  }
  var strokeWidth = Math.max(
    2,
    Math.round(configuredStrokeWidth * (charHW / configuredCharHW)),
  );
  function getHintAfterMisses(value) {
    var parsed = parseInt(value, 10);
    return parsed > 0 ? parsed : false;
  }

  var strokeAfterMisses = getHintAfterMisses(WRITE_SETTINGS.hint_after_misses);
  var strokeLeniency = Number(WRITE_SETTINGS.stroke_leniency);
  if (!isFinite(strokeLeniency) || strokeLeniency <= 0) {
    strokeLeniency = 1;
  }
