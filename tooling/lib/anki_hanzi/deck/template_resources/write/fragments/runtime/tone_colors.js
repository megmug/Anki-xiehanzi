  // change color
  var stroke_color = "#555";
  var outline_color = "#DDD";
  var drawing_color = "#333";

  if (document.body.classList.contains("night_mode")) {
    stroke_color = "#ffffff";
    outline_color = "#5B5B5B";
    drawing_color = "#fff";
  }

  function getToneColor(char) {
    stroke_color = "#555";
    if (document.body.classList.contains("night_mode")) {
      stroke_color = "#ffffff";
    }
    switch (char) {
      case "tone1":
        return "#f44336";
      case "tone2":
        return "#ff9800";
      case "tone3":
        return "#4caf50";
      case "tone4":
        return "#2196f3";
      case "tone0":
        return stroke_color;
      case "tone5":
        return stroke_color;
    }
  }

  function pinyinToneData(pinyinText, wrapperClass) {
    var colorizedHTML = pinyinWrapper().colorized_HTML_string_from_string(
      pinyinText,
      wrapperClass,
      ["tone0", "tone1", "tone2", "tone3", "tone4"],
    );
    if (!colorizedHTML) {
      return {
        html: null,
        toneClasses: [],
      };
    }

    var container = document.createElement("div");
    container.innerHTML = colorizedHTML;
    var wrapperElement = container.querySelector("." + wrapperClass);
    if (!wrapperElement) {
      return {
        html: colorizedHTML,
        toneClasses: [],
      };
    }

    var toneClasses = [];
    for (var i = 0; i < wrapperElement.children.length; i++) {
      toneClasses.push(wrapperElement.children[i].className);
    }
    return {
      html: colorizedHTML,
      toneClasses: toneClasses,
    };
  }

  function renderPinyinDisplay() {
    var pinyinText = "{{Pinyin}}";
    var pinyinDiv = document.getElementById("char_pinyin");
    if (!pinyinDiv) {
      return [];
    }

    var data = pinyinToneData(pinyinText, "pinYinWrapper");
    if (data.html) {
      pinyinDiv.innerHTML = data.html;
    } else {
      pinyinDiv.textContent = pinyinText;
    }
    return data.toneClasses;
  }

  function firstPinyinReading(pinyinText) {
    return String(pinyinText || "").split("/")[0].trim();
  }

  function colorWriterHanzi() {
    var charDiv = document.getElementById("char_sim");
    if (!charDiv) {
      return;
    }

    var text = charDiv.textContent || "";
    var toneClasses = pinyinToneData(
      firstPinyinReading("{{Pinyin}}"),
      "writerToneProbe",
    ).toneClasses;
    if (!text || toneClasses.length !== text.length) {
      return;
    }

    charDiv.innerHTML = "";
    for (var i = 0; i < text.length; i++) {
      var span = document.createElement("span");
      span.className = toneClasses[i];
      span.textContent = text[i];
      charDiv.appendChild(span);
    }
  }

  function setStrokeColor(i) {
    var toneClasses = renderPinyinDisplay();
    if (!toneClasses[i]) {
      return;
    }

    if (WRITE_SETTINGS.stroke_tone_color) {
      var toneColor = getToneColor(toneClasses[i]);
      if (!toneColor) {
        return;
      }
      drawing_color = toneColor;
      stroke_color = toneColor;
    }
  }

  colorWriterHanzi();
