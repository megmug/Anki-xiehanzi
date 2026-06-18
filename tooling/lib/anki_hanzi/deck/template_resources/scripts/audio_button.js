  function setupAudioButton() {
    var button = document.getElementById("btnPlayAudio");
    if (!button) return;
    if (collectAudioElements().length === 0) {
      button.style.display = "none";
      return;
    }
    button.onclick = function () {
      playAudio();
    };
  }
