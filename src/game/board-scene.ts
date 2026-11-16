import type * as Phaser from 'phaser';
import './board-scene.css';

interface BoardPieceView {
  side: 'w' | 'b';
  symbol?: string;
  disc?: boolean;
  king?: boolean;
}

export interface BoardSquareView {
  square: number;
  coordinate: string;
  label: string;
  piece?: BoardPieceView | null;
  marks?: number;
  locked?: boolean;
  last?: boolean;
  selected?: boolean;
  assigned?: boolean;
  checked?: boolean;
  target?: boolean;
  canMove?: boolean;
  canPlace?: boolean;
}

export interface DuelCellView {
  mark?: 'X' | 'O' | '';
  winning?: boolean;
  disabled?: boolean;
  label: string;
}

interface GridView<Cell> {
  render(cells: readonly Cell[]): void;
  refreshTheme(): void;
  focus(index?: number, options?: FocusOptions): void;
  destroy(): void;
}

const cellSize = 80;

function boardTheme(parent: HTMLElement) {
  const style = getComputedStyle(parent);
  const css = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
  const color = (name: string, fallback: string) => {
    const value = css(name, fallback);
    return Number.parseInt((/^#[0-9a-f]{6}$/i.test(value) ? value : fallback).slice(1), 16);
  };
  return {
    light: color('--tile-light', '#9bad9b'),
    dark: color('--tile-dark', '#3e5a4a'),
    lastLight: color('--last-light', '#b7a875'),
    lastDark: color('--last-dark', '#9a8954'),
    selected: color('--selected-tile', '#a8bc92'),
    selectedEdge: color('--selected-edge', '#304d3a'),
    checked: color('--checked', '#d28979'),
    targetLight: color('--target-light', '#254b39'),
    targetDark: color('--target-dark', '#d7e8cb'),
    brass: color('--brass', '#e9bc68'),
    brassEdge: color('--brass-edge', '#745120'),
    contrast: color('--board-contrast', '#17271e'),
    paper: color('--paper', '#212a25'),
    line: color('--line-strong', '#7c9084'),
    hover: color('--hover', '#29382f'),
    xInk: color('--x-ink', '#f0c980'),
    xSurface: color('--x-surface', '#483925'),
    oInk: color('--o-ink', '#c0dbc7'),
    oSurface: color('--o-surface', '#30493b'),
    coordLight: css('--coord-light', '#203329'),
    coordDark: css('--coord-dark', '#f3f5eb'),
    coordActive: css('--coord-active', '#17241c'),
    pieceShadow: css('--piece-shadow', 'rgba(18, 32, 25, .55)'),
    pieceFont: css('--type-piece', '"Segoe UI Symbol", "DejaVu Sans", serif'),
    coordinateFont: css('--type-coordinate', 'Consolas, monospace'),
    pieces: {
      w: {
        ink: css('--white-piece', '#fbf4da'),
        stroke: css('--white-stroke', '#304336'),
        crown: css('--brass-edge', '#745120'),
        disc: color('--disc-white', '#eee4cb'),
        rim: color('--disc-white-rim', '#927f57'),
        base: color('--disc-white-base', '#c8b993'),
      },
      b: {
        ink: css('--black-piece', '#182621'),
        stroke: css('--black-stroke', '#b3c6b7'),
        crown: css('--brass', '#e9bc68'),
        disc: color('--disc-black', '#21312a'),
        rim: color('--disc-black-rim', '#a7b7aa'),
        base: color('--disc-black-base', '#14291f'),
      },
    },
  };
}

type BoardTheme = ReturnType<typeof boardTheme>;
type Point = { x: number; y: number };

interface GridOptions<Cell extends { label: string }> {
  size: number;
  buttonClass: string;
  draw(scene: Phaser.Scene, cells: readonly Cell[], theme: BoardTheme): void;
  drawHover(graphics: Phaser.GameObjects.Graphics, index: number, cell: Cell, theme: BoardTheme): void;
  updateButton(button: HTMLButtonElement, cell: Cell, index: number): void;
  press?: (index: number, cell: Cell) => void;
}

function mountGrid<Cell extends { label: string }>(
  parent: HTMLElement,
  { size, buttonClass, draw, drawHover, updateButton, press }: GridOptions<Cell>,
): GridView<Cell> {
  const side = size * cellSize;
  const stage = document.createElement('div');
  stage.className = 'phaser-grid-stage';
  stage.setAttribute('aria-hidden', 'true');
  const status = document.createElement('p');
  status.className = 'phaser-grid-status';
  status.setAttribute('role', 'status');
  status.hidden = true;
  const keys = document.createElement('div');
  keys.className = 'phaser-grid-keys';
  keys.style.setProperty('--grid-size', String(size));
  parent.classList.add('phaser-grid');
  parent.append(stage, status);
  if (press) parent.append(keys);

  let theme = boardTheme(parent);
  let cells: readonly Cell[] = [];
  let hovered = -1;
  let focused = 0;
  let scene: Phaser.Scene | undefined;
  let hoverGraphics: Phaser.GameObjects.Graphics | undefined;
  let game: Phaser.Game | undefined;
  let starting = false;
  let destroyed = false;
  let touchActivation: { time: number; index: number } | undefined;
  const buttons = press ? Array.from({ length: size ** 2 }, (_, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `phaser-grid-key ${buttonClass}`;
    button.tabIndex = index === 0 ? 0 : -1;
    button.addEventListener('click', () => activate(index));
    button.addEventListener('focus', () => setFocused(index));
    button.addEventListener('keydown', event => {
      const next = adjacentIndex(index, size, event.key);
      if (next === undefined) return;
      event.preventDefault();
      focus(next, { preventScroll: true });
    });
    keys.append(button);
    return button;
  }) : [];

  function setFocused(index: number) {
    buttons.forEach((button, position) => {
      button.tabIndex = position === index ? 0 : -1;
    });
    focused = index;
  }

  function focus(index = focused, options?: FocusOptions) {
    const button = buttons[index];
    button?.focus(options);
  }

  function activate(index: number) {
    const cell = cells[index];
    if (!press || !cell || parent.inert || buttons[index]?.getAttribute('aria-disabled') === 'true') return;
    setFocused(index);
    press(index, cell);
  }

  function redraw() {
    if (!scene) return;
    draw(scene, cells, theme);
    hoverGraphics = scene.add.graphics().setDepth(3);
    redrawHover();
  }

  function redrawHover() {
    if (!hoverGraphics) return;
    hoverGraphics.clear();
    const cell = cells[hovered];
    if (cell) drawHover(hoverGraphics, hovered, cell, theme);
  }

  function cellAt(x: number, y: number) {
    if (x < 0 || y < 0 || x >= side || y >= side) return -1;
    return Math.floor(y / cellSize) * size + Math.floor(x / cellSize);
  }

  function setHovered(index: number) {
    if (hovered === index) return;
    hovered = index;
    redrawHover();
  }

  function refresh() {
    if (destroyed || !stage.clientWidth || !stage.clientHeight) return;
    if (game) {
      if (scene) {
        game.scale.getParentBounds();
        game.scale.refresh();
      }
      return;
    }
    if (starting) return;
    starting = true;
    status.hidden = false;
    status.textContent = 'กำลังโหลดกระดาน…';
    void import('phaser').then(engine => {
      if (destroyed) return;
      starting = false;
      if (!stage.clientWidth || !stage.clientHeight) return;
      startGame(engine);
    }).catch(() => {
      if (destroyed) return;
      status.textContent = 'โหลดกระดานไม่ได้ กรุณาโหลดหน้าใหม่';
    });
  }

  function startGame(engine: typeof import('phaser')) {
    const canvas = document.createElement('canvas');
    canvas.setAttribute('aria-hidden', 'true');
    if (press) canvas.style.cursor = 'pointer';
    // Update Phaser's pointer bounds if a dialog or scroll has moved the canvas.
    const updateBounds = () => game?.scale.updateBounds();
    for (const event of ['mousedown', 'mouseup', 'mousemove', 'touchstart', 'touchend']) {
      canvas.addEventListener(event, updateBounds, { capture: true, passive: true });
    }
    game = new engine.Game({
      type: engine.CANVAS,
      parent: stage,
      canvas,
      width: side,
      height: side,
      transparent: true,
      banner: false,
      autoFocus: false,
      fps: { limit: 30 },
      audio: { noAudio: true },
      input: {
        keyboard: false,
        mouse: press ? { preventDefaultMove: false, preventDefaultWheel: false } : false,
        touch: press ? { capture: false } : false,
        windowEvents: false,
      },
      scale: { mode: engine.Scale.FIT },
      scene: {
        create(this: Phaser.Scene) {
          scene = this;
          status.hidden = true;
          redraw();
          if (!press) return;
          this.input.on(engine.Input.Events.POINTER_MOVE, (pointer: Phaser.Input.Pointer) => {
            if (!pointer.wasTouch) setHovered(cellAt(pointer.x, pointer.y));
          });
          this.input.on(engine.Input.Events.GAME_OUT, () => setHovered(-1));
          this.input.on(engine.Input.Events.POINTER_UP, (pointer: Phaser.Input.Pointer) => {
            if (pointer.wasCanceled || pointer.downElement !== canvas || (!pointer.wasTouch && pointer.button !== 0)) return;
            const index = cellAt(pointer.x, pointer.y);
            if (index < 0 || index !== cellAt(pointer.downX, pointer.downY)) return;
            const time = pointer.event.timeStamp;
            if (pointer.wasTouch) {
              touchActivation = { index, time };
            } else if (touchActivation?.index === index && time >= touchActivation.time && time - touchActivation.time < 500) {
              return;
            }
            activate(index);
          });
        },
      },
    });
  }

  const observer = new ResizeObserver(refresh);
  observer.observe(stage);
  refresh();

  return {
    render(next) {
      cells = next;
      buttons.forEach((button, index) => {
        const cell = cells[index];
        if (!cell) return;
        button.setAttribute('aria-label', cell.label);
        updateButton(button, cell, index);
      });
      refresh();
      redraw();
    },
    refreshTheme() {
      theme = boardTheme(parent);
      redraw();
    },
    focus,
    destroy() {
      destroyed = true;
      observer.disconnect();
      game?.destroy(true);
      stage.remove();
      status.remove();
      keys.remove();
    },
  };
}

function adjacentIndex(index: number, size: number, key: string) {
  switch (key) {
    case 'ArrowLeft': return index % size > 0 ? index - 1 : index;
    case 'ArrowRight': return index % size < size - 1 ? index + 1 : index;
    case 'ArrowUp': return index >= size ? index - size : index;
    case 'ArrowDown': return index < size * (size - 1) ? index + size : index;
    default: return undefined;
  }
}

function cellPoint(index: number, size: number): Point {
  return { x: index % size * cellSize, y: Math.floor(index / size) * cellSize };
}

function strokeTile(g: Phaser.GameObjects.Graphics, { x, y }: Point, color: number, inset = 1, width = 3) {
  g.lineStyle(width, color).strokeRect(x + inset, y + inset, cellSize - 2 * inset, cellSize - 2 * inset);
}

function drawDisc(scene: Phaser.Scene, g: Phaser.GameObjects.Graphics, center: Point, piece: BoardPieceView, theme: BoardTheme) {
  const colors = theme.pieces[piece.side];
  const { x } = center;
  const y = center.y - (piece.king ? 4 : 1);
  const radius = 26;
  g.fillStyle(0x111a15, 0.45).fillCircle(x, y + (piece.king ? 6 : 3), radius + 0.5);
  if (piece.king) {
    g.fillStyle(colors.rim).fillCircle(x, y + 4, radius);
    g.fillStyle(colors.base).fillCircle(x, y + 3, radius);
  }
  g.fillStyle(colors.base).fillCircle(x, y, radius);
  g.fillStyle(colors.disc).fillCircle(x, y - 2, radius - 0.75);
  g.lineStyle(1.5, colors.rim).strokeCircle(x, y, radius).strokeCircle(x, y - 2, 18);
  if (piece.king) {
    scene.add.text(x, y - 3, '♛', {
      fontFamily: theme.pieceFont,
      fontSize: '39px',
      color: colors.crown,
    }).setOrigin(0.5);
  }
}

function drawPiece(scene: Phaser.Scene, g: Phaser.GameObjects.Graphics, center: Point, piece: BoardPieceView, theme: BoardTheme) {
  if (piece.disc) {
    drawDisc(scene, g, center, piece, theme);
    return;
  }
  if (!piece.symbol) return;
  const colors = theme.pieces[piece.side];
  scene.add.text(center.x, center.y - 3, piece.symbol, {
    fontFamily: theme.pieceFont,
    fontSize: '62px',
    color: colors.ink,
    stroke: colors.stroke,
    strokeThickness: 1.4,
    shadow: { color: theme.pieceShadow, offsetY: 2, blur: 2, fill: true },
  }).setOrigin(0.5);
}

function drawMarkers(g: Phaser.GameObjects.Graphics, { x, y }: Point, square: BoardSquareView, theme: BoardTheme) {
  const marks = Math.min(square.marks ?? 0, 2);
  for (let count = 0; count < marks; count++) {
    const left = x + 13 + count * 11;
    const top = y + 58;
    const points = [
      { x: left, y: top },
      { x: left + 8, y: top + 8 },
      { x: left, y: top + 16 },
      { x: left - 8, y: top + 8 },
    ];
    g.fillStyle(theme.brass).fillPoints(points, true);
    g.lineStyle(1, theme.brassEdge).strokePoints(points, true);
  }
  if (square.locked) {
    g.fillStyle(theme.contrast).fillRoundedRect(x + 54, y + 5, 21, 21, 4);
    g.lineStyle(1.5, theme.brass).beginPath().arc(x + 64.5, y + 14, 4, Math.PI, 2 * Math.PI).strokePath();
    g.fillStyle(theme.brass).fillRoundedRect(x + 59, y + 14, 11, 8, 1.5);
  }
}

function drawBoard(
  scene: Phaser.Scene,
  cells: readonly BoardSquareView[],
  theme: BoardTheme,
) {
  scene.children.removeAll(true);
  const tiles = scene.add.graphics();
  const pieces = scene.add.graphics();
  const markers = scene.add.graphics().setDepth(1);
  cells.forEach((square, index) => {
    const point = cellPoint(index, 8);
    const center = { x: point.x + cellSize / 2, y: point.y + cellSize / 2 };
    const dark = (index % 8 + Math.floor(index / 8)) % 2 === 1;
    let background = dark ? theme.dark : theme.light;
    if (square.last) background = dark ? theme.lastDark : theme.lastLight;
    if (square.selected) background = theme.selected;
    if (square.checked) background = theme.checked;
    tiles.fillStyle(background).fillRect(point.x, point.y, cellSize, cellSize);
    if (square.selected) strokeTile(tiles, point, theme.selectedEdge);
    if (square.assigned) {
      strokeTile(tiles, point, theme.brassEdge, 1);
      strokeTile(tiles, point, theme.brass, 3, 2);
    }
    if (square.target) {
      if (square.piece) {
        tiles.lineStyle(4, theme.selectedEdge).strokeCircle(center.x, center.y, 34);
        tiles.lineStyle(2.5, theme.targetDark).strokeCircle(center.x, center.y, 34);
      } else {
        const color = square.last ? theme.contrast : dark ? theme.targetDark : theme.targetLight;
        tiles.fillStyle(color).fillCircle(center.x, center.y, 8.6);
      }
    }
    if (square.piece) drawPiece(scene, pieces, center, square.piece, theme);
    drawMarkers(markers, point, square, theme);

    const coordStyle = {
      fontFamily: theme.coordinateFont,
      fontStyle: 'bold',
      fontSize: '16px',
      color: square.last || square.selected || square.checked ? theme.coordActive : dark ? theme.coordDark : theme.coordLight,
    };
    if (index % 8 === 0) {
      scene.add.text(point.x + 4, point.y + 3, square.coordinate.slice(1), coordStyle).setDepth(2);
    }
    if (index >= 56) {
      scene.add.text(point.x + 75, point.y + 77, square.coordinate.slice(0, 1), coordStyle).setOrigin(1).setDepth(2);
    }
  });
}

export function mountGameBoard(parent: HTMLElement, onSquare?: (square: number) => void) {
  return mountGrid<BoardSquareView>(parent, {
    size: 8,
    buttonClass: 'square',
    draw: drawBoard,
    drawHover(graphics, index, square, theme) {
      if (square.canPlace || square.canMove) strokeTile(graphics, cellPoint(index, 8), theme.targetDark, 2);
    },
    updateButton(button, square) {
      button.dataset.square = String(square.square);
      button.dataset.coordinate = square.coordinate;
      button.dataset.marks = String(square.marks ?? 0);
      button.dataset.disc = square.piece?.disc ? square.piece.side : '';
      button.dataset.locked = String(!!square.locked);
      button.setAttribute('aria-pressed', String(!!square.selected));
    },
    press: onSquare ? (_, square) => onSquare(square.square) : undefined,
  });
}

function drawDuel(
  scene: Phaser.Scene,
  cells: readonly DuelCellView[],
  theme: BoardTheme,
) {
  scene.children.removeAll(true);
  const g = scene.add.graphics();
  g.fillStyle(theme.line).fillRect(0, 0, 3 * cellSize, 3 * cellSize);
  cells.forEach((cell, index) => {
    const { x, y } = cellPoint(index, 3);
    const fill = cell.winning ? (cell.mark === 'X' ? theme.xSurface : theme.oSurface) : theme.paper;
    g.fillStyle(fill).fillRect(x + 0.5, y + 0.5, cellSize - 1, cellSize - 1);
    if (cell.mark === 'X') {
      const near = 23;
      const far = 57;
      g.lineStyle(6, theme.xInk).lineBetween(x + near, y + near, x + far, y + far);
      g.lineBetween(x + far, y + near, x + near, y + far);
      g.fillStyle(theme.xInk).fillCircle(x + near, y + near, 3).fillCircle(x + far, y + far, 3)
        .fillCircle(x + far, y + near, 3).fillCircle(x + near, y + far, 3);
    } else if (cell.mark === 'O') {
      g.lineStyle(6, theme.oInk).strokeCircle(x + cellSize / 2, y + cellSize / 2, 20);
    }
  });
}

export function mountDuelBoard(parent: HTMLElement, onCell: (index: number) => void) {
  return mountGrid<DuelCellView>(parent, {
    size: 3,
    buttonClass: 'duel-cell',
    draw: drawDuel,
    drawHover(graphics, index, cell, theme) {
      if (cell.disabled) return;
      const { x, y } = cellPoint(index, 3);
      graphics.fillStyle(theme.hover).fillRect(x + 0.5, y + 0.5, cellSize - 1, cellSize - 1);
    },
    updateButton(button, cell, index) {
      button.dataset.cell = String(index);
      button.dataset.mark = cell.mark ?? '';
      button.dataset.winning = String(!!cell.winning);
      // Keep occupied cells reachable so keyboard users can read marks and preserve their grid position.
      button.setAttribute('aria-disabled', String(!!cell.disabled));
    },
    press: onCell,
  });
}
