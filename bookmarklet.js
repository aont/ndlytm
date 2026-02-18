(function(){
  const w = document.getElementById("HTML5PlayerFrame")?.contentWindow || window
  const url = "https://aont.github.io/ndlytm/#?jsonInput=" + encodeURIComponent(JSON.stringify({
    "Cookie": document.cookie,
    "BaseURL": window.location.origin,
    "PlayListsTracks":w.PlayListsTracks,
    "AlbumArt": w.document.querySelector("#album-link > img").src
  }))
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.target = '_blank';
  anchor.click();
  anchor.remove()
})();
