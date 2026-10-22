/**
 * Interactive Tripwire Canvas Overlay
 * Enables drag-and-drop handles for calibrating bag crossing line over live CCTV feed.
 */
class TripwireCanvas {
  constructor(canvasId, videoImgId) {
    this.canvas = document.getElementById(canvasId);
    this.ctx = this.canvas.getContext('2d');
    this.videoImg = document.getElementById(videoImgId);

    // Virtual video resolution (defaults to 1280x720)
    this.videoWidth = 1280;
    this.videoHeight = 720;

    // Line coordinates in video pixel space
    this.p1 = { x: 300, y: 450 };
    this.p2 = { x: 980, y: 450 };

    this.draggingPoint = null; // 'p1' | 'p2' | 'both' | null
    this.isDrawingNew = false;
    this.handleRadius = 10;

    this.initEvents();
    this.resizeCanvas();
    window.addEventListener('resize', () => this.resizeCanvas());
    this.render();
  }

  resizeCanvas() {
    const rect = this.videoImg.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) {
      this.canvas.width = rect.width;
      this.canvas.height = rect.height;
      this.render();
    }
  }

  // Convert video coordinates (1280x720) to canvas screen coordinates
  toScreen(pt) {
    const sx = this.canvas.width / this.videoWidth;
    const sy = this.canvas.height / this.videoHeight;
    return { x: pt.x * sx, y: pt.y * sy };
  }

  // Convert canvas screen coordinates to video coordinates (1280x720)
  toVideo(screenPt) {
    const sx = this.videoWidth / this.canvas.width;
    const sy = this.videoHeight / this.canvas.height;
    return {
      x: Math.round(screenPt.x * sx),
      y: Math.round(screenPt.y * sy)
    };
  }

  setLine(x1, y1, x2, y2) {
    this.p1 = { x: x1, y: y1 };
    this.p2 = { x: x2, y: y2 };
    this.render();
  }

  getLine() {
    return {
      x1: this.p1.x,
      y1: this.p1.y,
      x2: this.p2.x,
      y2: this.p2.y
    };
  }

  initEvents() {
    const getPos = (e) => {
      const rect = this.canvas.getBoundingClientRect();
      const clientX = e.touches ? e.touches[0].clientX : e.clientX;
      const clientY = e.touches ? e.touches[0].clientY : e.clientY;
      return {
        x: clientX - rect.left,
        y: clientY - rect.top
      };
    };

    const dist = (p1, p2) => Math.hypot(p1.x - p2.x, p1.y - p2.y);

    const onDown = (e) => {
      this.resizeCanvas();
      const pos = getPos(e);
      const s1 = this.toScreen(this.p1);
      const s2 = this.toScreen(this.p2);

      if (dist(pos, s1) <= this.handleRadius * 1.5) {
        this.draggingPoint = 'p1';
      } else if (dist(pos, s2) <= this.handleRadius * 1.5) {
        this.draggingPoint = 'p2';
      } else {
        // Draw new line
        this.isDrawingNew = true;
        const vPos = this.toVideo(pos);
        this.p1 = { ...vPos };
        this.p2 = { ...vPos };
      }
    };

    const onMove = (e) => {
      if (!this.draggingPoint && !this.isDrawingNew) return;
      const pos = getPos(e);
      const vPos = this.toVideo(pos);

      if (this.draggingPoint === 'p1') {
        this.p1 = vPos;
      } else if (this.draggingPoint === 'p2') {
        this.p2 = vPos;
      } else if (this.isDrawingNew) {
        this.p2 = vPos;
      }
      this.render();
    };

    const onUp = () => {
      this.draggingPoint = null;
      this.isDrawingNew = false;
      this.render();
    };

    this.canvas.addEventListener('mousedown', onDown);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);

    this.canvas.addEventListener('touchstart', (e) => { e.preventDefault(); onDown(e); });
    window.addEventListener('touchmove', onMove);
    window.addEventListener('touchend', onUp);
  }

  render() {
    if (!this.canvas.width || !this.canvas.height) return;
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

    const s1 = this.toScreen(this.p1);
    const s2 = this.toScreen(this.p2);

    // Glowing main line
    ctx.save();
    ctx.strokeStyle = 'rgba(0, 240, 255, 0.4)';
    ctx.lineWidth = 8;
    ctx.beginPath();
    ctx.moveTo(s1.x, s1.y);
    ctx.lineTo(s2.x, s2.y);
    ctx.stroke();

    ctx.strokeStyle = '#00f0ff';
    ctx.lineWidth = 3;
    ctx.stroke();

    // Direction normal arrow in center of line
    const mx = (s1.x + s2.x) / 2;
    const my = (s1.y + s2.y) / 2;
    const dx = s2.x - s1.x;
    const dy = s2.y - s1.y;
    const len = Math.hypot(dx, dy) || 1;
    // normal vector pointing clockwise / downwards in screen coords (IN direction)
    const nx = (-dy / len) * 28;
    const ny = (dx / len) * 28;

    // Draw IN Arrow (green)
    ctx.strokeStyle = '#10b981';
    ctx.fillStyle = '#10b981';
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(mx, my);
    ctx.lineTo(mx + nx, my + ny);
    ctx.stroke();

    // Arrowhead
    const angle = Math.atan2(ny, nx);
    ctx.beginPath();
    ctx.moveTo(mx + nx, my + ny);
    ctx.lineTo(mx + nx - 10 * Math.cos(angle - Math.PI / 6), my + ny - 10 * Math.sin(angle - Math.PI / 6));
    ctx.lineTo(mx + nx - 10 * Math.cos(angle + Math.PI / 6), my + ny - 10 * Math.sin(angle + Math.PI / 6));
    ctx.fill();

    // Endpoints Handles
    // Start Handle (Green)
    ctx.fillStyle = '#10b981';
    ctx.shadowColor = '#10b981';
    ctx.shadowBlur = 10;
    ctx.beginPath();
    ctx.arc(s1.x, s1.y, this.handleRadius, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 2;
    ctx.stroke();

    // End Handle (Red)
    ctx.fillStyle = '#f43f5e';
    ctx.shadowColor = '#f43f5e';
    ctx.shadowBlur = 10;
    ctx.beginPath();
    ctx.arc(s2.x, s2.y, this.handleRadius, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 2;
    ctx.stroke();

    // Text labels
    ctx.shadowBlur = 0;
    ctx.font = '600 12px Outfit, sans-serif';
    ctx.fillStyle = '#ffffff';
    ctx.fillText('START', s1.x - 20, s1.y - 14);
    ctx.fillText('END', s2.x - 14, s2.y - 14);
    ctx.restore();
  }
}

window.TripwireCanvas = TripwireCanvas;
