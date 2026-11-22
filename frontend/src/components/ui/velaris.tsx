import { useEffect, useRef } from 'react';

/*
 * Animated simplex-noise gradient (adapted from the 21st.dev "Velaris" component).
 * Changes from the original, for scroll smoothness and battery (Frontend-Implemented 5f):
 * - renders at half resolution (soft gradients look identical) and at most 30 frames per second;
 * - pauses while off-screen (IntersectionObserver) or while the tab is hidden;
 * - draws one still frame when reduced motion is requested;
 * - falls back to a CSS gradient when WebGL is unavailable or the shader fails;
 * - colours are parsed once, not every frame; GL resources are released on unmount;
 * - height follows the content unless `height` is given (the original forced 100vh);
 * - edges fade to `bg` instead of black, so a light theme works (used app-wide by AppBackground).
 */

const vertexShaderGLSL = `
attribute vec2 position;
varying vec2 vUv;
void main() {
  vUv = position * 0.5 + 0.5;
  gl_Position = vec4(position, 0.0, 1.0);
}
`;

const fragmentShaderGLSL = `
precision mediump float;
varying vec2 vUv;

uniform vec2  u_resolution;
uniform float u_time;
uniform float u_grain;
uniform vec3  u_colors[4];
uniform vec3  u_bg;

vec3 permute(vec3 x) { return mod(((x*34.0)+1.0)*x, 289.0); }

float snoise(vec2 v){
  const vec4 C = vec4(0.211324865405187, 0.366025403784439,
           -0.577350269189626, 0.024390243902439);
  vec2 i  = floor(v + dot(v, C.yy) );
  vec2 x0 = v -   i + dot(i, C.xx);
  vec2 i1 = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
  vec4 x12 = x0.xyxy + C.xxzz;
  x12.xy -= i1;
  i = mod(i, 289.0);
  vec3 p = permute( permute( i.y + vec3(0.0, i1.y, 1.0 ))
  + i.x + vec3(0.0, i1.x, 1.0 ));
  vec3 m = max(0.5 - vec3(dot(x0,x0), dot(x12.xy,x12.xy),
    dot(x12.zw,x12.zw)), 0.0);
  m = m*m ;
  m = m*m ;
  vec3 x = 2.0 * fract(p * C.www) - 1.0;
  vec3 h = abs(x) - 0.5;
  vec3 ox = floor(x + 0.5);
  vec3 a0 = x - ox;
  m *= 1.79284291400159 - 0.85373472095314 * ( a0*a0 + h*h );
  vec3 g;
  g.x  = a0.x  * x0.x  + h.x  * x0.y;
  g.yz = a0.yz * x12.xz + h.yz * x12.yw;
  return 130.0 * dot(m, g);
}

void main() {
  vec2 uv = vUv;
  float ratio = u_resolution.x / u_resolution.y;
  vec2 p = uv - 0.5;
  p.x *= ratio;

  float t = u_time * 0.1;

  float n1 = snoise(p * 0.4 + vec2(t * 0.2, -t * 0.3));
  float n2 = snoise(p * 0.55 + vec2(-t * 0.15, t * 0.25) + n1 * 0.25);
  float n3 = snoise(p * 0.75 + vec2(t * 0.1, -t * 0.2) + n2 * 0.2);

  vec3 col = u_bg;

  float dist = length(p) * 1.5;
  float vignette = 1.0 - smoothstep(0.3, 1.2, dist);

  col = mix(col, u_colors[0], smoothstep(-0.2, 0.5, n1) * 0.85);
  col = mix(col, u_colors[1], smoothstep(-0.1, 0.6, n2) * 0.7);
  col = mix(col, u_colors[2], smoothstep(-0.3, 0.4, n3) * 0.6);
  col = mix(col, u_colors[3], smoothstep(0.0, 0.7, n1 * n2) * 0.5);

  float glow = smoothstep(0.8, 0.0, dist) * 0.3;
  col += u_colors[1] * glow;

  col = mix(u_bg, col, vignette); // edges fade to the page colour, not to black

  float grain = fract(sin(dot(uv, vec2(12.9898, 78.233))) * 43758.5453 + u_time);
  col += (grain - 0.5) * u_grain * 0.1;

  gl_FragColor = vec4(col, 1.0);
}
`;

export interface VelarisProps {
  bg?: string;
  colors?: string[];
  speed?: number;
  /** false: draw one still frame (low-end devices, Data Saver). */
  animate?: boolean;
  grain?: number;
  /** CSS height; omit to size to the content. */
  height?: string;
  className?: string;
  children?: React.ReactNode;
}

/** Dark theme greens (green-800, green-700, emerald-900, stone-950) keep white text readable. */
const DEFAULT_COLORS = ['#166534', '#15803d', '#064e3b', '#0c0a09'];
const FRAME_MS = 1000 / 30;
const RESOLUTION_SCALE = 0.5;

const hexToRgb = (hex: string): [number, number, number] => {
  const h = hex.replace('#', '');
  return [parseInt(h.slice(0, 2), 16) / 255, parseInt(h.slice(2, 4), 16) / 255, parseInt(h.slice(4, 6), 16) / 255];
};

const Velaris = ({
  bg = '#0c0a09',
  colors = DEFAULT_COLORS,
  speed = 2.0,
  animate = true,
  grain = 0.3,
  height,
  className,
  children,
}: VelarisProps) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const colorKey = colors.slice(0, 4).join(',');

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return undefined;

    const gl = canvas.getContext('webgl', { antialias: false, alpha: false, powerPreference: 'low-power' });
    if (!gl) return undefined; // the CSS gradient on the container stays visible

    const compile = (type: number, src: string) => {
      const shader = gl.createShader(type);
      if (!shader) return null;
      gl.shaderSource(shader, src);
      gl.compileShader(shader);
      return gl.getShaderParameter(shader, gl.COMPILE_STATUS) ? shader : null;
    };
    const vs = compile(gl.VERTEX_SHADER, vertexShaderGLSL);
    const fs = compile(gl.FRAGMENT_SHADER, fragmentShaderGLSL);
    const program = gl.createProgram();
    if (!vs || !fs || !program) return undefined;
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return undefined;
    gl.useProgram(program);

    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const pos = gl.getAttribLocation(program, 'position');
    gl.enableVertexAttribArray(pos);
    gl.vertexAttribPointer(pos, 2, gl.FLOAT, false, 0, 0);

    const locs = {
      res: gl.getUniformLocation(program, 'u_resolution'),
      time: gl.getUniformLocation(program, 'u_time'),
      grain: gl.getUniformLocation(program, 'u_grain'),
      colors: gl.getUniformLocation(program, 'u_colors'),
      bg: gl.getUniformLocation(program, 'u_bg'),
    };
    // Constant uniforms are set once.
    gl.uniform1f(locs.grain, grain);
    gl.uniform3f(locs.bg, ...hexToRgb(bg));
    gl.uniform3fv(locs.colors, new Float32Array(colorKey.split(',').flatMap(hexToRgb)));

    const draw = (t: number) => {
      gl.uniform2f(locs.res, canvas.width, canvas.height);
      gl.uniform1f(locs.time, t * 0.001 * speed);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    };

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    let visible = true;
    let raf = 0;
    let last = 0;

    const loop = (t: number) => {
      raf = 0;
      if (!visible || document.hidden || reducedMotion.matches || !animate) return;
      if (t - last >= FRAME_MS) {
        last = t;
        draw(t);
      }
      raf = requestAnimationFrame(loop);
    };
    const start = () => {
      if (reducedMotion.matches || !animate) draw(4000); // one still frame
      else if (!raf) raf = requestAnimationFrame(loop);
    };

    const resize = () => {
      canvas.width = Math.max(1, Math.round(container.clientWidth * RESOLUTION_SCALE));
      canvas.height = Math.max(1, Math.round(container.clientHeight * RESOLUTION_SCALE));
      gl.viewport(0, 0, canvas.width, canvas.height);
      draw(last || 4000);
    };
    const ro = new ResizeObserver(resize);
    ro.observe(container);

    const io = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      if (visible) start();
    });
    io.observe(container);

    document.addEventListener('visibilitychange', start);
    reducedMotion.addEventListener('change', start);
    start();

    return () => {
      ro.disconnect();
      io.disconnect();
      document.removeEventListener('visibilitychange', start);
      reducedMotion.removeEventListener('change', start);
      if (raf) cancelAnimationFrame(raf);
      gl.deleteBuffer(buffer);
      gl.deleteProgram(program);
      gl.deleteShader(vs);
      gl.deleteShader(fs);
    };
  }, [bg, colorKey, speed, grain, animate]);

  return (
    <div
      ref={containerRef}
      style={height ? { height, backgroundColor: bg } : { backgroundColor: bg }}
      // Plain concatenation: cn() would add tailwind-merge (about 10 KB gzip) for one class string.
      // Without WebGL the solid `bg` colour shows.
      className={`relative w-full overflow-hidden ${className ?? ''}`}
    >
      <canvas ref={canvasRef} aria-hidden="true" className="pointer-events-none absolute inset-0 h-full w-full" />
      <div className="relative z-10 h-full w-full">{children}</div>
    </div>
  );
};

export default Velaris;
