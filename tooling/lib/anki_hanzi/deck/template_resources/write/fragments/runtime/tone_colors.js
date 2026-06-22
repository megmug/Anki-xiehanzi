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

  function setStrokeColor(i) {
    var pinyinText = "{{Pinyin}}";
    var pinyinDiv = document.getElementById("char_pinyin");
    if (!pinyinDiv) {
      return;
    }
    var colorizeHTML = pinyinWrapper().colorized_HTML_string_from_string(
      pinyinText,
      "pinYinWrapper",
      ["tone0", "tone1", "tone2", "tone3", "tone4"],
    );
    if (colorizeHTML) {
      pinyinDiv.innerHTML = colorizeHTML;
    } else {
      pinyinDiv.textContent = pinyinText;
    }
    var pinyinWrapperElement = document.querySelector(".pinYinWrapper");
    if (!pinyinWrapperElement || !pinyinWrapperElement.children[i]) {
      return;
    }
    var charClass = pinyinWrapperElement.children;

    if (WRITE_SETTINGS.stroke_tone_color) {
      var toneColor = getToneColor(charClass[i].className);
      if (!toneColor) {
        return;
      }
      drawing_color = toneColor;
      stroke_color = toneColor;
    }
  }
