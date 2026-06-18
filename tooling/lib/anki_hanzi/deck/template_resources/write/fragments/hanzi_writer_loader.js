  // Local hanzi-writer-data JSON files packaged as Anki media
  var url_hanzi = "";

  function bundleCharDataLoader(char) {
    return new Promise(function (resolve, reject) {
      if (window.hanziWriterData && window.hanziWriterData[char]) {
        resolve(window.hanziWriterData[char]);
      } else {
        reject(new Error("No data for character: " + char));
      }
    });
  }
  /* __HANZI_WRITER_BUNDLE__ */
