  function showHide(selector, isShow, style) {
    document.querySelectorAll(selector).forEach(function (element) {
      element.style.display = isShow ? style || "inline" : "none";
    });
  }
