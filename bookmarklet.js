(function(){
  const w = document.getElementById("HTML5PlayerFrame")?.contentWindow || window
  const url = "https://aont.github.io/ndlytm/#?jsonInput=" + encodeURIComponent(JSON.stringify({"Cookie":document.cookie,"BaseURL":window.location.origin,"PlayListsTracks":w.PlayListsTracks}))
  window.open(url);
})();
