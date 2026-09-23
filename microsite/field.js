(function () {
  var canvas = document.getElementById('lf-backdrop');
  if (!canvas) return;
  var ctx = canvas.getContext('2d');
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var lines = [];
  var time = 0;

  function resize() {
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.floor(innerWidth * dpr);
    canvas.height = Math.floor(innerHeight * dpr);
    canvas.style.width = innerWidth + 'px';
    canvas.style.height = innerHeight + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    lines = [];
    for (var i = -2; i < 22; i++) lines.push(i / 20);
    draw();
  }

  function draw() {
    var w = innerWidth, h = innerHeight;
    ctx.clearRect(0, 0, w, h);
    var dark = !(window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches);
    ctx.strokeStyle = dark ? 'rgba(168,215,183,.15)' : 'rgba(47,109,73,.13)';
    ctx.lineWidth = 1;
    lines.forEach(function (seed, index) {
      ctx.beginPath();
      for (var x = -20; x <= w + 20; x += 22) {
        var y = h * (.18 + seed * .78) + Math.sin(x / 170 + seed * 9 + time * .00018) * (18 + seed * 20) + Math.sin(x / 420 + index) * 18;
        if (x === -20) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.stroke();
    });
    if (!reduce) { time += 16; requestAnimationFrame(draw); }
  }

  addEventListener('resize', resize, { passive: true });
  resize();
})();
