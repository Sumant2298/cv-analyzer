/**
 * interview-room.js
 * Vanilla JS engine for the immersive AI mock interview room.
 * 7 classes, zero framework dependencies.
 * Works with DOM element IDs defined in session_room.html.
 */

/* ------------------------------------------------------------------ */
/*  1. TimerManager                                                    */
/* ------------------------------------------------------------------ */
class TimerManager {
    constructor(displayEl, durationMinutes) {
        this.display = displayEl;
        this.remaining = durationMinutes * 60;
        this.interval = null;
        this.onExpire = null;
    }

    start(onExpire) {
        this.onExpire = onExpire;
        this._tick();
        this.interval = setInterval(() => this._tick(), 1000);
    }

    _tick() {
        if (this.remaining <= 0) {
            clearInterval(this.interval);
            this.display.textContent = '0:00';
            this.onExpire?.();
            return;
        }
        const m = Math.floor(this.remaining / 60);
        const s = this.remaining % 60;
        this.display.textContent = `${m}:${s.toString().padStart(2, '0')}`;

        if (this.remaining === 120) {
            this.display.classList.add('text-amber-400');
        }
        if (this.remaining <= 60) {
            this.display.classList.remove('text-amber-400');
            this.display.classList.add('text-red-400');
        }
        this.remaining--;
    }

    stop() {
        clearInterval(this.interval);
        this.interval = null;
    }
}

/* ------------------------------------------------------------------ */
/*  2. AvatarEngine                                                    */
/* ------------------------------------------------------------------ */
class AvatarEngine {
    constructor(frameEl) {
        this.frame = frameEl;
        this.currentMouthOpen = 0;
        this.blinkTimeout = null;
        this.nodInterval = null;
        this.animationFrame = null;
        this._speaking = false;
    }

    /* --- idle loop (no overlays — avatar is pure SVG) ------------- */
    startIdleAnimation() {
        /* Blink/mouth overlays removed. Speaking feedback is via
           speaking-tilt + speaking-glow CSS on the frame. */
    }

    scheduleBlink() { /* no-op — overlays removed */ }
    blink() { /* no-op — overlays removed */ }

    /* --- expressions ---------------------------------------------- */
    setExpression(name) {
        this.frame.classList.remove('thinking', 'smile', 'nod', 'concerned');
        if (name && name !== 'neutral') {
            this.frame.classList.add(name);
            if (name === 'nod') setTimeout(() => this.frame.classList.remove('nod'), 500);
            if (name === 'smile') setTimeout(() => this.frame.classList.remove('smile'), 2000);
        }
    }

    /* Mouth/blink overlay divs removed. Speaking visual feedback is
       handled by speaking-tilt + speaking-glow CSS classes on #avatar-frame. */
    startMouthAnimation() { this._speaking = true; }
    startSimulatedMouth() { this._speaking = true; }
    stopMouthAnimation() { this._speaking = false; cancelAnimationFrame(this.animationFrame); }

    /* --- nodding while candidate speaks --------------------------- */
    startNodding() {
        this.nodInterval = setInterval(() => {
            this.setExpression('nod');
        }, 3000 + Math.random() * 2000);
    }

    stopNodding() {
        clearInterval(this.nodInterval);
        this.nodInterval = null;
    }

    /* --- helpers -------------------------------------------------- */
    estimateSyllables(text) {
        return text.split(/\s+/).reduce((count, word) => {
            word = word.toLowerCase().replace(/[^a-z]/g, '');
            if (word.length <= 3) return count + 1;
            const vowelGroups = word.match(/[aeiouy]+/g);
            return count + (vowelGroups ? vowelGroups.length : 1);
        }, 0);
    }

    destroy() {
        this._speaking = false;
        clearTimeout(this.blinkTimeout);
        clearInterval(this.nodInterval);
        cancelAnimationFrame(this.animationFrame);
    }
}

/* ------------------------------------------------------------------ */
/*  3. AudioPipeline                                                   */
/* ------------------------------------------------------------------ */
class AudioPipeline {
    constructor() {
        this.audioContext = null;
        this.analyser = null;
        this.frequencyData = null;
        this.recognition = null;
        this.synthesis = window.speechSynthesis;
        this.preferredVoice = null;
        this.micStream = null;
        this.micAnalyser = null;
        this.micData = null;
        this.isListening = false;
        this.finalTranscript = '';
        this.interimTranscript = '';
        this.silenceTimer = null;
        this.useElevenLabs = false;
        this._elevenLabsChecked = false;
        this._silenceCheck = null;

        /* callbacks */
        this.onSpeakStart = null;
        this.onSpeakEnd = null;
        this.onTranscript = null;
        this.onSilenceAutoStop = null;

        this.initRecognition();
        this.selectVoice();
    }

    /* --- audio context (lazy, needs user gesture) ----------------- */
    ensureAudioContext() {
        if (!this.audioContext) {
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
            this.analyser = this.audioContext.createAnalyser();
            this.analyser.fftSize = 256;
            this.frequencyData = new Uint8Array(this.analyser.frequencyBinCount);
        }
        if (this.audioContext.state === 'suspended') {
            this.audioContext.resume();
        }
    }

    /* --- speech recognition --------------------------------------- */
    initRecognition() {
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SR) {
            this.recognitionState = 'error';
            return;
        }
        this.recognitionState = 'idle';
        this.onRecognitionStateChange = null;
        this.recognition = new SR();
        this.recognition.continuous = true;
        this.recognition.interimResults = true;
        this.recognition.lang = 'en-IN';
        this.recognition.maxAlternatives = 1;

        this.recognition.onstart = () => {
            this.recognitionState = 'listening';
            this._restartCount = 0; // Reset only when recognition actually starts
            this.onRecognitionStateChange?.('listening');
            console.log('[STT] Recognition started');
        };

        this.recognition.onaudiostart = () => {
            console.log('[STT] Audio capture started');
        };

        this.recognition.onresult = (event) => {
            this._noSpeechCount = 0;
            // NOTE: Don't reset _restartCount here — it breaks backoff logic.
            // _restartCount is reset in onstart instead.
            let interim = '';
            for (let i = event.resultIndex; i < event.results.length; i++) {
                const t = event.results[i][0].transcript;
                if (event.results[i].isFinal) {
                    this.finalTranscript += t + ' ';
                    this.onTranscript?.(this.finalTranscript.trim(), true);
                } else {
                    interim += t;
                }
            }
            this.interimTranscript = interim;
            this.onTranscript?.((this.finalTranscript + interim).trim(), false);
            this.silenceTimer = Date.now();
        };

        this._noSpeechCount = 0;
        this._restartCount = 0;
        this.recognition.onerror = (e) => {
            console.warn('[STT] Error:', e.error);
            if (e.error === 'aborted') return;
            if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
                this.recognitionState = 'error';
                this.onRecognitionStateChange?.('error');
                this.onTranscript?.('Microphone access denied. Check browser permissions.', false);
                return;
            }
            if (e.error === 'network') {
                this.recognitionState = 'error';
                this.onRecognitionStateChange?.('error');
                this.onTranscript?.('Speech recognition unavailable. Check internet connection.', false);
                return;
            }
            if (e.error === 'no-speech') {
                this._noSpeechCount++;
                if (this._noSpeechCount >= 3) {
                    this._noSpeechCount = 0;
                    this.onTranscript?.('No speech detected. Speak louder or use the Type button.', false);
                }
                return;
            }
            console.error('[STT] Unhandled error:', e.error);
        };

        this.recognition.onend = () => {
            console.log('[STT] Recognition ended, isListening:', this.isListening);
            if (this.isListening && this.recognitionState !== 'error') {
                this._restartCount++;
                if (this._restartCount > 10) {
                    this.recognitionState = 'error';
                    this.onRecognitionStateChange?.('error');
                    this.onTranscript?.('Speech recognition stopped. Please use the Type button.', false);
                    return;
                }
                const delay = Math.min(100 * this._restartCount, 1000);
                setTimeout(() => {
                    if (this.isListening) {
                        try { this.recognition.start(); } catch (err) {
                            console.error('[STT] Restart failed:', err);
                        }
                    }
                }, delay);
            }
        };
    }

    /* --- voice selection (prefer Indian English) ------------------- */
    selectVoice() {
        const load = () => {
            const voices = this.synthesis.getVoices();
            this.preferredVoice =
                voices.find(v => v.lang === 'en-IN' && v.name.includes('Google')) ||
                voices.find(v => v.lang === 'en-IN') ||
                voices.find(v => v.lang.startsWith('en-IN')) ||
                voices.find(v => v.name.includes('Google') && v.lang.startsWith('en')) ||
                voices.find(v => v.lang.startsWith('en-') && v.name.includes('Natural')) ||
                voices.find(v => v.lang.startsWith('en')) ||
                null;
        };
        load();
        if (this.synthesis.onvoiceschanged !== undefined) {
            this.synthesis.onvoiceschanged = load;
        }
    }

    /* --- listening ------------------------------------------------ */
    startListening() {
        if (!this.recognition) return false;
        this.ensureAudioContext();
        this.finalTranscript = '';
        this.interimTranscript = '';
        this.isListening = true;
        this._noSpeechCount = 0;
        this._restartCount = 0;
        this.recognitionState = 'starting';
        this.onRecognitionStateChange?.('starting');
        this.silenceTimer = Date.now();
        try {
            this.recognition.start();
        } catch (e) {
            console.error('[STT] Start failed:', e);
            this.recognitionState = 'error';
            this.onRecognitionStateChange?.('error');
            return false;
        }

        this._silenceCheck = setInterval(() => {
            if (!this.isListening) return;
            if (
                this.finalTranscript.trim().length > 0 &&
                Date.now() - this.silenceTimer > 5000
            ) {
                this.onSilenceAutoStop?.();
            }
        }, 500);
        return true;
    }

    stopListening() {
        this.isListening = false;
        clearInterval(this._silenceCheck);
        try { this.recognition?.stop(); } catch (_) { /* */ }
        return this.finalTranscript.trim();
    }

    getTranscript() {
        return this.finalTranscript.trim();
    }

    /* --- TTS orchestration ---------------------------------------- */
    async speak(text) {
        this.ensureAudioContext();

        /* try ElevenLabs if already known to work */
        if (this.useElevenLabs) {
            const ok = await this.speakElevenLabs(text);
            if (ok) return;
            /* ElevenLabs failed — fall through to browser */
        }

        /* first-time probe — use the actual text instead of wasting credits on "test" */
        if (!this._elevenLabsChecked) {
            this._elevenLabsChecked = true;
            try {
                const ok = await this.speakElevenLabs(text);
                if (ok) {
                    this.useElevenLabs = true;
                    return;
                }
            } catch (_) { /* fall through to Web Speech */ }
            console.warn('[TTS] ElevenLabs unavailable, falling back to browser voice. Set ELEVENLABS_API_KEY in environment.');
        }

        return this.speakWebSpeech(text);
    }

    async speakElevenLabs(text) {
        try {
            /* Ensure AudioContext is running (Chrome autoplay policy) */
            if (this.audioContext.state === 'suspended') {
                await this.audioContext.resume();
            }

            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), 30000);
            console.log('[TTS] Requesting ElevenLabs audio for', text.length, 'chars...');
            const resp = await fetch('/api/interview/tts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text }),
                signal: controller.signal,
            });
            clearTimeout(timeout);

            if (resp.status !== 200) {
                console.warn('[TTS] ElevenLabs returned status', resp.status);
                return false;
            }

            const arrayBuffer = await resp.arrayBuffer();
            console.log('[TTS] Received', arrayBuffer.byteLength, 'bytes');
            if (!arrayBuffer || arrayBuffer.byteLength < 100) {
                console.warn('[TTS] Audio too small:', arrayBuffer.byteLength);
                return false;
            }

            const audioBuffer = await this.audioContext.decodeAudioData(arrayBuffer.slice(0));
            console.log('[TTS] Decoded audio:', audioBuffer.duration.toFixed(1), 's');

            const source = this.audioContext.createBufferSource();
            source.buffer = audioBuffer;
            source.connect(this.analyser);
            this.analyser.connect(this.audioContext.destination);

            this.onSpeakStart?.();
            source.start();

            return new Promise((resolve) => {
                source.onended = () => {
                    this.onSpeakEnd?.();
                    resolve(true);
                };
                /* Safety: if onended doesn't fire, force-resolve after audio duration + 1s */
                setTimeout(() => {
                    this.onSpeakEnd?.();
                    resolve(true);
                }, (audioBuffer.duration + 1) * 1000);
            });
        } catch (e) {
            console.error('[TTS] ElevenLabs error:', e.message || e);
            return false;
        }
    }

    speakWebSpeech(text) {
        return new Promise((resolve) => {
            this.synthesis.cancel();
            const utter = new SpeechSynthesisUtterance(text);
            utter.rate = 0.95;
            utter.pitch = 1.0;
            utter.volume = 1.0;
            if (this.preferredVoice) utter.voice = this.preferredVoice;

            let resolved = false;
            const safeResolve = () => {
                if (resolved) return;
                resolved = true;
                this.onSpeakEnd?.();
                resolve();
            };

            utter.onstart = () => this.onSpeakStart?.();
            utter.onend = safeResolve;
            utter.onerror = safeResolve;

            /* Chrome bug workaround: onend doesn't fire for long text (>200 chars).
               Estimate speech duration at ~150 wpm and add a 2-second buffer. */
            const wordCount = text.split(/\s+/).length;
            const estimatedMs = (wordCount / 2.5) * 1000 + 2000;
            setTimeout(() => {
                if (!resolved) {
                    console.warn('[TTS] Chrome onend bug — forcing speech end after', estimatedMs, 'ms');
                    this.synthesis.cancel();
                    safeResolve();
                }
            }, estimatedMs);

            this.synthesis.speak(utter);
        });
    }

    /* --- analyser data -------------------------------------------- */
    getFrequencyData() {
        if (this.analyser && this.frequencyData) {
            this.analyser.getByteFrequencyData(this.frequencyData);
            return this.frequencyData;
        }
        return null;
    }

    async setupMicAnalyser(stream) {
        this.ensureAudioContext();
        this.micStream = stream;
        const source = this.audioContext.createMediaStreamSource(stream);
        this.micAnalyser = this.audioContext.createAnalyser();
        this.micAnalyser.fftSize = 256;
        this.micData = new Uint8Array(this.micAnalyser.frequencyBinCount);
        source.connect(this.micAnalyser);
    }

    getMicLevel() {
        if (!this.micAnalyser || !this.micData) return 0;
        this.micAnalyser.getByteFrequencyData(this.micData);
        const sum = this.micData.reduce((a, b) => a + b, 0);
        return sum / this.micData.length / 255;
    }

    destroy() {
        this.isListening = false;
        clearInterval(this._silenceCheck);
        try { this.recognition?.stop(); } catch (_) { /* */ }
        this.synthesis.cancel();
        this.audioContext?.close();
    }
}

/* ------------------------------------------------------------------ */
/*  4. WebcamManager                                                   */
/* ------------------------------------------------------------------ */
class WebcamManager {
    constructor(videoEl, fallbackEl) {
        this.video = videoEl;
        this.fallback = fallbackEl;
        this.stream = null;
        this.cameraEnabled = true;
    }

    async requestCamera() {
        try {
            this.stream = await navigator.mediaDevices.getUserMedia({
                video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' },
                audio: true,
            });
            this.video.srcObject = this.stream;
            this.video.classList.remove('hidden');
            this.fallback.classList.add('hidden');
            return this.stream;
        } catch (e) {
            console.warn('Camera unavailable:', e.name);
            this.video.classList.add('hidden');
            this.fallback.classList.remove('hidden');
            try {
                this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                return this.stream;
            } catch (_) {
                return null;
            }
        }
    }

    toggleCamera() {
        if (!this.stream) return false;
        const track = this.stream.getVideoTracks()[0];
        if (!track) return false;
        track.enabled = !track.enabled;
        this.cameraEnabled = track.enabled;
        if (track.enabled) {
            this.video.classList.remove('hidden');
            this.fallback.classList.add('hidden');
        } else {
            this.video.classList.add('hidden');
            this.fallback.classList.remove('hidden');
        }
        return track.enabled;
    }

    destroy() {
        this.stream?.getTracks().forEach(t => t.stop());
    }
}

/* ------------------------------------------------------------------ */
/*  5. TranscriptManager                                               */
/* ------------------------------------------------------------------ */
class TranscriptManager {
    constructor(containerEl) {
        this.container = containerEl;
    }

    addMessage(role, text, metadata = {}) {
        const wrapper = document.createElement('div');
        wrapper.className = 'px-4 py-1.5';

        const escaped = this.escapeHtml(text);
        const isCode = text.startsWith('```');
        const displayText = isCode
            ? `<pre class="bg-slate-900 text-emerald-300 p-3 rounded-lg text-xs overflow-x-auto mt-1"><code>${this.escapeHtml(text.replace(/```\n?/g, ''))}</code></pre>`
            : escaped;

        if (role === 'interviewer') {
            let badge = '';
            if (metadata.questionType) {
                const colors = {
                    warmup: 'bg-emerald-500/20 text-emerald-400',
                    behavioral: 'bg-blue-500/20 text-blue-400',
                    technical: 'bg-violet-500/20 text-violet-400',
                    coding: 'bg-amber-500/20 text-amber-400',
                    situational: 'bg-rose-500/20 text-rose-400',
                    follow_up: 'bg-slate-500/20 text-slate-400',
                    closing: 'bg-indigo-500/20 text-indigo-400',
                };
                const cls = colors[metadata.questionType] || 'bg-slate-500/20 text-slate-400';
                const label = metadata.questionType.replace('_', ' ').toUpperCase();
                badge =
                    `<span class="inline-block text-[9px] font-bold px-1.5 py-0.5 rounded-full mb-1 ${cls}">${label}</span><br>`;
            }
            wrapper.innerHTML = `
                <div class="flex gap-2.5 max-w-[85%]">
                    <div class="w-7 h-7 rounded-full bg-gradient-to-br from-brand-500 to-indigo-600
                                flex items-center justify-center text-white text-[10px] font-bold
                                flex-shrink-0 mt-1">P</div>
                    <div class="bg-slate-800 border border-slate-700 rounded-2xl rounded-tl-sm px-4 py-2.5">
                        ${badge}
                        <p class="text-sm text-slate-200 leading-relaxed">${displayText}</p>
                    </div>
                </div>`;
        } else {
            wrapper.innerHTML = `
                <div class="flex justify-end">
                    <div class="max-w-[80%] bg-brand-600 text-white rounded-2xl rounded-br-sm px-4 py-2.5">
                        <p class="text-sm leading-relaxed">${displayText}</p>
                    </div>
                </div>`;
        }

        this.container.appendChild(wrapper);
        this.scrollToBottom();
    }

    /**
     * Typewriter effect — types out the message character-by-character.
     * Returns a Promise that resolves when the typing animation is done.
     */
    addMessageTypewriter(role, text, metadata = {}, charDelay = 20) {
        return new Promise((resolve) => {
            const wrapper = document.createElement('div');
            wrapper.className = 'px-4 py-1.5';

            const escaped = this.escapeHtml(text);

            let badge = '';
            if (metadata.questionType) {
                const colors = {
                    warmup: 'bg-emerald-500/20 text-emerald-400',
                    behavioral: 'bg-blue-500/20 text-blue-400',
                    technical: 'bg-violet-500/20 text-violet-400',
                    coding: 'bg-amber-500/20 text-amber-400',
                    situational: 'bg-rose-500/20 text-rose-400',
                    follow_up: 'bg-slate-500/20 text-slate-400',
                    closing: 'bg-indigo-500/20 text-indigo-400',
                };
                const cls = colors[metadata.questionType] || 'bg-slate-500/20 text-slate-400';
                const label = metadata.questionType.replace('_', ' ').toUpperCase();
                badge =
                    `<span class="inline-block text-[9px] font-bold px-1.5 py-0.5 rounded-full mb-1 ${cls}">${label}</span><br>`;
            }

            wrapper.innerHTML = `
                <div class="flex gap-2.5 max-w-[85%]">
                    <div class="w-7 h-7 rounded-full bg-gradient-to-br from-brand-500 to-indigo-600
                                flex items-center justify-center text-white text-[10px] font-bold
                                flex-shrink-0 mt-1">P</div>
                    <div class="bg-slate-800 border border-slate-700 rounded-2xl rounded-tl-sm px-4 py-2.5">
                        ${badge}
                        <p class="text-sm text-slate-200 leading-relaxed typewriter-target"></p>
                    </div>
                </div>`;
            this.container.appendChild(wrapper);

            const target = wrapper.querySelector('.typewriter-target');
            const chars = text.split('');
            let idx = 0;

            const typeNext = () => {
                if (idx < chars.length) {
                    target.textContent += chars[idx];
                    idx++;
                    this.scrollToBottom();
                    setTimeout(typeNext, charDelay);
                } else {
                    resolve();
                }
            };
            typeNext();
        });
    }

    addTypingIndicator() {
        if (document.getElementById('typing-indicator')) return;
        const el = document.createElement('div');
        el.id = 'typing-indicator';
        el.className = 'px-4 py-1.5';
        el.innerHTML = `
            <div class="flex gap-2.5">
                <div class="w-7 h-7 rounded-full bg-gradient-to-br from-brand-500 to-indigo-600
                            flex items-center justify-center text-white text-[10px] font-bold
                            flex-shrink-0 mt-1">P</div>
                <div class="bg-slate-800 border border-slate-700 rounded-2xl rounded-tl-sm px-4 py-3">
                    <div class="typing-dots"><span></span><span></span><span></span></div>
                </div>
            </div>`;
        this.container.appendChild(el);
        this.scrollToBottom();
    }

    removeTypingIndicator() {
        document.getElementById('typing-indicator')?.remove();
    }

    scrollToBottom() {
        this.container.scrollTop = this.container.scrollHeight;
    }

    escapeHtml(text) {
        const d = document.createElement('div');
        d.textContent = text;
        return d.innerHTML;
    }
}

/* ------------------------------------------------------------------ */
/*  6. CodeEditorManager                                               */
/* ------------------------------------------------------------------ */
class CodeEditorManager {
    constructor(containerEl, outputEl) {
        this.container = containerEl;
        this.output = outputEl;
        this.editor = null;
        this.ready = false;
        this._initPromise = null;
    }

    init() {
        if (this._initPromise) return this._initPromise;
        this._initPromise = new Promise((resolve) => {
            if (this.editor) { resolve(); return; }
            if (typeof require === 'undefined') {
                /* Monaco loader not on page yet -- skip gracefully */
                console.warn('Monaco loader not available');
                resolve();
                return;
            }
            require.config({
                paths: { vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs' },
            });
            require(['vs/editor/editor.main'], () => {
                monaco.editor.defineTheme('interview-dark', {
                    base: 'vs-dark',
                    inherit: true,
                    rules: [],
                    colors: {
                        'editor.background': '#0f172a',
                        'editor.foreground': '#e2e8f0',
                        'editorLineNumber.foreground': '#475569',
                        'editor.lineHighlightBackground': '#1e293b',
                        'editor.selectionBackground': '#334155',
                    },
                });
                this.editor = monaco.editor.create(this.container, {
                    value: '',
                    language: 'python',
                    theme: 'interview-dark',
                    minimap: { enabled: false },
                    fontSize: 14,
                    lineNumbers: 'on',
                    scrollBeyondLastLine: false,
                    automaticLayout: true,
                    padding: { top: 12, bottom: 12 },
                    bracketPairColorization: { enabled: true },
                    autoClosingBrackets: 'always',
                    tabSize: 4,
                    wordWrap: 'on',
                });
                this.ready = true;
                resolve();
            });
        });
        return this._initPromise;
    }

    setLanguage(lang) {
        if (this.editor) {
            monaco.editor.setModelLanguage(this.editor.getModel(), lang);
        }
        const sel = document.getElementById('code-language');
        if (sel) sel.value = lang;
    }

    getValue() {
        return this.editor ? this.editor.getValue() : '';
    }

    setValue(code) {
        if (this.editor) this.editor.setValue(code);
    }

    reset() {
        if (this.editor) this.editor.setValue('');
    }

    showOutput(data) {
        const statusColors = {
            Accepted: 'text-emerald-400',
            'Runtime Error': 'text-red-400',
            'Time Limit Exceeded': 'text-amber-400',
            'Compilation Error': 'text-red-400',
        };
        const color = statusColors[data.status] || 'text-slate-400';
        const esc = (t) => this.escapeHtml(t || '');

        let html = `<div class="space-y-2">
            <div class="flex items-center gap-2">
                <span class="text-[10px] font-bold ${color}">${esc(data.status)}</span>
                ${data.time ? `<span class="text-[10px] text-slate-500">${esc(data.time)}</span>` : ''}
            </div>`;
        if (data.stdout) {
            html += `<div><p class="text-[10px] font-bold text-slate-500 mb-1">Output</p>
                <pre class="text-xs text-slate-300 bg-slate-900 p-2 rounded">${esc(data.stdout)}</pre></div>`;
        }
        if (data.stderr) {
            html += `<div><p class="text-[10px] font-bold text-red-500 mb-1">Error</p>
                <pre class="text-xs text-red-300 bg-slate-900 p-2 rounded">${esc(data.stderr)}</pre></div>`;
        }
        if (data.compile_output) {
            html += `<div><p class="text-[10px] font-bold text-amber-500 mb-1">Compile</p>
                <pre class="text-xs text-amber-300 bg-slate-900 p-2 rounded">${esc(data.compile_output)}</pre></div>`;
        }
        html += '</div>';
        this.output.innerHTML = html;
    }

    escapeHtml(text) {
        const d = document.createElement('div');
        d.textContent = text;
        return d.innerHTML;
    }
}

/* ------------------------------------------------------------------ */
/*  7. InterviewRoom  (orchestrator)                                   */
/* ------------------------------------------------------------------ */
class InterviewRoom {
    /**
     * @param {Object} config
     * @param {string} config.sessionId
     * @param {number} config.duration        - minutes
     * @param {string} config.interviewType
     * @param {string} config.persona
     * @param {string} config.difficulty
     * @param {string} config.targetRole
     * @param {string} config.userName
     */
    constructor(config) {
        this.config = config;

        this.state = {
            questionNumber: 0,
            totalExpected: 0,
            isRecording: false,
            isProcessing: false,
            isSpeaking: false,
            currentRequiresCode: false,
            activeTab: 'transcript',
            panelCollapsed: true,
            answerStartTime: null,
            micLevelRAF: null,
        };

        /* sub-systems */
        this.avatar = new AvatarEngine(document.getElementById('avatar-frame'));
        this.audio = new AudioPipeline();
        this.webcam = new WebcamManager(
            document.getElementById('webcam-video'),
            document.getElementById('webcam-fallback'),
        );
        this.transcript = new TranscriptManager(document.getElementById('transcript-messages'));
        this.codeEditor = new CodeEditorManager(
            document.getElementById('monaco-container'),
            document.getElementById('code-output'),
        );
        this.timer = new TimerManager(
            document.getElementById('timer-text'),
            config.duration,
        );

        /* cached DOM refs */
        this.dom = {
            micBtn: document.getElementById('mic-btn'),
            camBtn: document.getElementById('cam-btn'),
            typeBtn: document.getElementById('type-btn'),
            skipBtn: document.getElementById('skip-btn'),
            endBtn: document.getElementById('end-call-btn'),
            panelToggle: document.getElementById('panel-collapse-btn'),
            bottomPanel: document.getElementById('bottom-panel'),
            runCodeBtn: document.getElementById('code-run-btn'),
            submitCodeBtn: document.getElementById('code-submit-btn'),
            resetCodeBtn: document.getElementById('code-reset-btn'),
            submitTextBtn: document.getElementById('type-send-btn'),
            textInput: document.getElementById('type-input'),
            typeModal: document.getElementById('type-modal'),
            liveCaption: document.getElementById('live-caption'),
            aiWave: document.getElementById('ai-speaking-wave'),
            userWave: document.getElementById('user-speaking-wave'),
            codeLang: document.getElementById('code-language'),
            avatarSubtitle: document.getElementById('avatar-subtitle'),
        };

        this.init();
    }

    /* ============================================================== */
    /*  INIT                                                           */
    /* ============================================================== */
    async init() {
        this.bindEvents();
        this.avatar.startIdleAnimation();
        this.timer.start(() => this.endInterview());

        /* Sync collapse icons with initial collapsed state */
        document.getElementById('collapse-icon-down')?.classList.add('hidden');
        document.getElementById('collapse-icon-up')?.classList.remove('hidden');

        const stream = await this.webcam.requestCamera();
        if (stream) {
            await this.audio.setupMicAnalyser(stream);
        }

        await this.loadSession();
    }

    /* ============================================================== */
    /*  EVENT BINDING                                                  */
    /* ============================================================== */
    bindEvents() {
        /* control bar */
        this.dom.micBtn.onclick = () => this.toggleMic();
        this.dom.camBtn.onclick = () => this.toggleCamera();
        this.dom.typeBtn.onclick = () => this.toggleTypeModal();
        this.dom.skipBtn.onclick = () => this.skipQuestion();
        this.dom.endBtn.onclick = () => this.endInterview();

        /* tab switching (only tabs with data-tab attribute) */
        document.querySelectorAll('.panel-tab[data-tab]').forEach((btn) => {
            btn.onclick = () => this.switchTab(btn.dataset.tab);
        });

        /* panel toggle */
        this.dom.panelToggle.onclick = () => this.togglePanel();

        /* code buttons */
        this.dom.runCodeBtn.onclick = () => this.runCode();
        this.dom.submitCodeBtn.onclick = () => this.submitCode();
        this.dom.resetCodeBtn.onclick = () => this.codeEditor.reset();

        /* language dropdown */
        if (this.dom.codeLang) {
            this.dom.codeLang.onchange = () => {
                this.codeEditor.setLanguage(this.dom.codeLang.value);
            };
        }

        /* text answer modal */
        this.dom.submitTextBtn.onclick = () => this.submitTextAnswer();
        this.dom.textInput.onkeydown = (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.submitTextAnswer();
            }
        };

        /* audio pipeline callbacks */
        this.audio.onSpeakStart = () => {
            this.state.isSpeaking = true;
            this.dom.aiWave?.classList.remove('hidden');
        };
        this.audio.onSpeakEnd = () => {
            this.state.isSpeaking = false;
            this.avatar.stopMouthAnimation();
            this.dom.aiWave?.classList.add('hidden');
            this.setCaption('');
        };
        this.audio.onTranscript = (text, isFinal) => {
            this.setCaption(text);
        };
        this.audio.onSilenceAutoStop = () => {
            if (this.state.isRecording) {
                this.toggleMic();
            }
        };

        /* speech recognition state feedback */
        this.audio.onRecognitionStateChange = (state) => {
            if (state === 'listening') {
                this.setCaption('🎙 Listening... speak now');
                this.dom.micBtn?.classList.remove('error-state');
                /* clear initial caption after 3s if no transcript yet */
                setTimeout(() => {
                    if (this.state.isRecording &&
                        this.audio.finalTranscript.length === 0 &&
                        this.audio.interimTranscript.length === 0) {
                        this.setCaption('🎙 Listening... speak now or use Type button');
                    }
                }, 3000);
            } else if (state === 'error') {
                this.dom.micBtn?.classList.add('error-state');
            } else if (state === 'starting') {
                this.setCaption('Starting microphone...');
            }
        };
    }

    /* ============================================================== */
    /*  SESSION LOADING (resume support)                               */
    /* ============================================================== */
    async loadSession() {
        try {
            const resp = await fetch(`/api/interview/session/${this.config.sessionId}`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();

            const session = data.session || data.data?.session || {};
            const exchanges = data.exchanges || data.data?.exchanges || [];
            this.state.totalExpected = session.total_expected || 0;

            /* replay past exchanges into transcript */
            let lastUnanswered = null;
            for (const ex of exchanges) {
                if (ex.question_text && !ex.answer_text) {
                    /* current unanswered question — skip instant display, will typewriter below */
                    lastUnanswered = ex;
                    this.state.questionNumber = ex.sequence || this.state.questionNumber + 1;
                    continue;
                }
                if (ex.question_text) {
                    this.transcript.addMessage('interviewer', ex.question_text, {
                        questionType: ex.question_type,
                    });
                    this.state.questionNumber = ex.sequence || this.state.questionNumber + 1;
                }
                if (ex.answer_text) {
                    this.transcript.addMessage('candidate', ex.answer_text);
                }
            }

            this.updateQuestionCounter();

            /* typewriter + speak the last unanswered question concurrently */
            if (lastUnanswered) {
                if (lastUnanswered.requires_code) {
                    this.state.currentRequiresCode = true;
                    this.switchTab('code');
                    if (lastUnanswered.code_language) {
                        await this.codeEditor.init();
                        this.codeEditor.setLanguage(lastUnanswered.code_language);
                    }
                }
                const qText = lastUnanswered.question_text;
                this.transcript.addMessage('interviewer', qText, { questionType: lastUnanswered.question_type });
                await this.speakInterviewerMessage(qText);

                /* Auto-start mic after Priya's first question */
                await this.sleep(600);
                if (!this.state.isRecording && !this.state.isProcessing && !this.state.isSpeaking) {
                    this.toggleMic();
                }
            }
        } catch (e) {
            console.error('Failed to load session:', e);
        }
    }

    /* ============================================================== */
    /*  MICROPHONE TOGGLE                                              */
    /* ============================================================== */
    toggleMic() {
        if (this.state.isProcessing || this.state.isSpeaking) return;

        const micBtn = this.dom.micBtn;

        if (this.state.isRecording) {
            /* --- stop recording --- */
            const transcript = this.audio.stopListening();
            this.state.isRecording = false;
            micBtn.classList.remove('active');
            this.avatar.stopNodding();
            this.dom.userWave?.classList.add('hidden');
            this.stopMicLevelAnimation();
            this.setCaption('');

            if (transcript.length > 0) {
                const elapsed = this.state.answerStartTime
                    ? Math.round((Date.now() - this.state.answerStartTime) / 1000)
                    : 0;
                this.submitAnswer(transcript, null, elapsed);
            }
        } else {
            /* --- start recording --- */
            this.audio.ensureAudioContext();
            const ok = this.audio.startListening();
            if (!ok) {
                this.setCaption('Speech recognition not available in this browser.');
                return;
            }
            this.state.isRecording = true;
            this.state.answerStartTime = Date.now();
            micBtn.classList.add('active');
            this.avatar.startNodding();
            this.dom.userWave?.classList.remove('hidden');
            this.startMicLevelAnimation();
        }
    }

    startMicLevelAnimation() {
        const animate = () => {
            if (!this.state.isRecording) return;
            const level = this.audio.getMicLevel();
            const spread = Math.round(level * 20);
            const opacity = 0.15 + level * 0.5;
            this.dom.micBtn.style.boxShadow =
                level > 0.02
                    ? `0 0 0 ${spread}px rgba(239, 68, 68, ${opacity})`
                    : 'none';
            this.state.micLevelRAF = requestAnimationFrame(animate);
        };
        animate();
    }

    stopMicLevelAnimation() {
        cancelAnimationFrame(this.state.micLevelRAF);
        this.dom.micBtn.style.boxShadow = 'none';
    }

    /* ============================================================== */
    /*  SUBMIT ANSWER  (core conversation loop)                        */
    /* ============================================================== */
    async submitAnswer(answerText, codeText = null, durationSeconds = 0) {
        if (this.state.isProcessing) return;
        this.state.isProcessing = true;
        this.disableControls(true);

        /* 1. show candidate message */
        this.transcript.addMessage('candidate', answerText);
        if (codeText) {
            this.transcript.addMessage('candidate', '```\n' + codeText + '\n```');
        }

        /* 2. typing indicator + avatar thinking */
        this.transcript.addTypingIndicator();
        this.avatar.setExpression('thinking');

        try {
            /* 3. POST answer to API */
            const resp = await fetch('/api/interview/answer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: this.config.sessionId,
                    answer_text: answerText,
                    code_text: codeText,
                    answer_duration_seconds: durationSeconds,
                }),
            });
            const data = await resp.json();

            /* handle interview ended */
            if (data.interview_ended) {
                this.transcript.removeTypingIndicator();
                this.cleanup();
                window.location.href = data.redirect_url || `/interview/feedback/${this.config.sessionId}`;
                return;
            }

            /* 4. natural pause */
            await this.sleep(500);

            /* 5. brief smile */
            this.avatar.setExpression('smile');
            await this.sleep(400);
            this.avatar.setExpression('neutral');

            /* 6. remove typing indicator, typewriter + TTS concurrently */
            this.transcript.removeTypingIndicator();

            const message = data.interviewer_message || data.message || '';
            this.state.questionNumber = data.question_number || this.state.questionNumber + 1;
            this.state.totalExpected = data.total_expected || this.state.totalExpected;
            this.updateQuestionCounter();

            /* show brief feedback if present (instant, not typewritered) */
            if (data.brief_feedback && typeof data.brief_feedback === 'string') {
                this.transcript.addMessage('interviewer', data.brief_feedback, {
                    questionType: 'follow_up',
                });
            }

            /* 7. Add message to transcript (hidden in collapsed panel) + speak with subtitle overlay */
            this.transcript.addMessage('interviewer', message, { questionType: data.question_type });
            await this.speakInterviewerMessage(message);

            /* 8. if requires_code, switch to code tab */
            if (data.requires_code) {
                this.state.currentRequiresCode = true;
                this.switchTab('code');
                this.expandPanel();
                await this.codeEditor.init();
                if (data.code_language) {
                    this.codeEditor.setLanguage(data.code_language);
                }
            } else {
                this.state.currentRequiresCode = false;
            }

            /* 9. Re-enable controls before auto-unmute */
            this.state.isProcessing = false;
            this.disableControls(false);

            /* 10. Auto-start mic for user's turn */
            await this.sleep(600);
            if (!this.state.isRecording && !this.state.isProcessing && !this.state.isSpeaking) {
                this.toggleMic();
            }
        } catch (e) {
            console.error('Submit answer error:', e);
            this.transcript.removeTypingIndicator();
            this.transcript.addMessage('interviewer',
                'Sorry, there was a connection issue. Please try again.', {});
        } finally {
            /* Guard: only clean up if still processing (error path) */
            if (this.state.isProcessing) {
                this.state.isProcessing = false;
                this.disableControls(false);
            }
        }
    }

    /* ============================================================== */
    /*  SPEAK INTERVIEWER MESSAGE  (TTS + avatar)                      */
    /* ============================================================== */
    async speakInterviewerMessage(text) {
        this.setCaption('🔊 Priya is speaking...');

        const resetSpeakingState = () => {
            this.state.isSpeaking = false;
            this.avatar.stopMouthAnimation();
            this.avatar.frame.classList.remove('speaking-tilt', 'speaking-glow');
            this.dom.aiWave?.classList.add('hidden');
            this.setCaption('');
            this.hideSubtitle(1000);
        };

        /* Fallback: if onSpeakStart doesn't fire within 3s, show subtitle anyway */
        const subtitleFallback = setTimeout(() => {
            if (!this.state.isSpeaking) {
                this.showSubtitle(text);
            }
        }, 3000);

        const origOnStart = this.audio.onSpeakStart;
        this.audio.onSpeakStart = () => {
            clearTimeout(subtitleFallback);
            this.state.isSpeaking = true;
            this.dom.aiWave?.classList.remove('hidden');
            this.avatar.frame.classList.add('speaking-tilt', 'speaking-glow');
            /* Show text as subtitle exactly when audio starts playing */
            this.showSubtitle(text);
        };

        const origOnEnd = this.audio.onSpeakEnd;
        this.audio.onSpeakEnd = () => resetSpeakingState();

        /* HARD TIMEOUT: If TTS hangs for any reason, force-cancel after 45s. */
        const hardTimeout = setTimeout(() => {
            console.warn('[TTS] Hard timeout — forcing speech end');
            this.audio.synthesis.cancel();
            resetSpeakingState();
        }, 45000);

        try {
            await this.audio.speak(text);
        } catch (e) {
            console.error('[TTS] speak() threw:', e);
        } finally {
            clearTimeout(hardTimeout);
            clearTimeout(subtitleFallback);
            resetSpeakingState();
            this.audio.onSpeakStart = origOnStart;
            this.audio.onSpeakEnd = origOnEnd;
        }
    }

    /* ============================================================== */
    /*  END INTERVIEW                                                  */
    /* ============================================================== */
    async endInterview() {
        if (this.state.isRecording) {
            this.audio.stopListening();
            this.state.isRecording = false;
        }
        this.timer.stop();
        this.disableControls(true);

        /* show full-screen processing overlay */
        this.showEndingOverlay();

        const fallbackUrl = `/interview/feedback/${this.config.sessionId}`;

        const attemptEnd = async () => {
            const controller = new AbortController();
            const fetchTimer = setTimeout(() => controller.abort(), 30000); // 30s hard limit
            try {
                const resp = await fetch('/api/interview/end', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ session_id: this.config.sessionId }),
                    signal: controller.signal,
                });
                clearTimeout(fetchTimer);
                if (!resp.ok) {
                    const errData = await resp.json().catch(() => ({}));
                    return { ok: false, redirect: errData.redirect_url || fallbackUrl };
                }
                const data = await resp.json();
                return { ok: true, redirect: data.redirect_url || fallbackUrl };
            } catch (e) {
                clearTimeout(fetchTimer);
                console.warn('[EndCall] fetch failed/aborted:', e.message);
                return { ok: false, redirect: fallbackUrl };
            }
        };

        try {
            let result = await attemptEnd();
            if (!result.ok) {
                /* auto-retry once after 3 seconds */
                this.showEndError('Generating feedback... Retrying...');
                await this.sleep(3000);
                result = await attemptEnd();
            }
            /* Always redirect — server includes redirect_url even on failure */
            this.cleanup();
            window.location.href = result.redirect;
        } catch (e) {
            console.error('End interview error:', e);
            this.cleanup();
            window.location.href = fallbackUrl;
        }
    }

    showEndingOverlay() {
        if (document.getElementById('ending-overlay')) return;
        const overlay = document.createElement('div');
        overlay.id = 'ending-overlay';
        overlay.className = 'ending-overlay';
        overlay.innerHTML = `
            <div class="ending-spinner"></div>
            <p class="ending-msg">Generating your feedback report...</p>
            <p class="ending-sub">This may take a few seconds</p>`;
        document.querySelector('.room-layout')?.appendChild(overlay) ||
            document.body.appendChild(overlay);
    }

    showEndError(msg) {
        const el = document.querySelector('.ending-msg');
        if (el) el.textContent = msg;
    }

    /* ============================================================== */
    /*  CODE EXECUTION                                                 */
    /* ============================================================== */
    async runCode() {
        const code = this.codeEditor.getValue();
        if (!code.trim()) return;

        const lang = this.dom.codeLang ? this.dom.codeLang.value : 'python';
        this.dom.runCodeBtn.disabled = true;
        this.dom.runCodeBtn.textContent = 'Running...';
        this.codeEditor.output.innerHTML =
            '<p class="text-xs text-slate-500 animate-pulse">Executing...</p>';

        try {
            const resp = await fetch('/api/interview/run-code', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code, language: lang, stdin: '' }),
            });
            const data = await resp.json();
            this.codeEditor.showOutput(data);
        } catch (e) {
            this.codeEditor.showOutput({
                status: 'Runtime Error',
                stderr: 'Network error: could not execute code.',
            });
        } finally {
            this.dom.runCodeBtn.disabled = false;
            this.dom.runCodeBtn.textContent = 'Run';
        }
    }

    submitCode() {
        const code = this.codeEditor.getValue();
        if (!code.trim()) return;
        const elapsed = this.state.answerStartTime
            ? Math.round((Date.now() - this.state.answerStartTime) / 1000)
            : 0;
        this.submitAnswer('Here is my code solution:', code, elapsed);
    }

    /* ============================================================== */
    /*  TAB / PANEL MANAGEMENT                                         */
    /* ============================================================== */
    switchTab(tab) {
        this.state.activeTab = tab;

        document.querySelectorAll('.panel-tab').forEach((btn) => {
            btn.classList.toggle('active', btn.dataset.tab === tab);
        });

        ['transcript', 'code', 'notes'].forEach((t) => {
            const el = document.getElementById(`tab-${t}`);
            if (el) el.classList.toggle('active', t === tab);
        });

        /* lazy-init Monaco on first code tab switch */
        if (tab === 'code') {
            this.codeEditor.init();
        }

        if (tab === 'transcript') {
            this.transcript.scrollToBottom();
        }
    }

    togglePanel() {
        this.state.panelCollapsed = !this.state.panelCollapsed;
        const panel = this.dom.bottomPanel;
        if (!panel) return;

        const iconDown = document.getElementById('collapse-icon-down');
        const iconUp = document.getElementById('collapse-icon-up');

        if (this.state.panelCollapsed) {
            panel.classList.add('collapsed');
            if (iconDown) iconDown.classList.add('hidden');
            if (iconUp) iconUp.classList.remove('hidden');
        } else {
            panel.classList.remove('collapsed');
            if (iconDown) iconDown.classList.remove('hidden');
            if (iconUp) iconUp.classList.add('hidden');
        }
    }

    expandPanel() {
        if (this.state.panelCollapsed) {
            this.togglePanel();
        }
    }

    /* ============================================================== */
    /*  CAMERA TOGGLE                                                  */
    /* ============================================================== */
    toggleCamera() {
        const enabled = this.webcam.toggleCamera();
        this.dom.camBtn.classList.toggle('active', enabled);
    }

    /* ============================================================== */
    /*  TYPE MODAL                                                     */
    /* ============================================================== */
    toggleTypeModal() {
        if (this.state.isProcessing || this.state.isSpeaking) return;
        const modal = this.dom.typeModal;
        if (!modal) return;

        const isOpen = !modal.classList.contains('hidden');
        if (isOpen) {
            modal.classList.add('hidden');
        } else {
            modal.classList.remove('hidden');
            this.dom.textInput.value = '';
            this.dom.textInput.focus();
            this.state.answerStartTime = this.state.answerStartTime || Date.now();
        }
    }

    submitTextAnswer() {
        const text = this.dom.textInput.value.trim();
        if (!text) return;
        this.dom.typeModal.classList.add('hidden');
        const elapsed = this.state.answerStartTime
            ? Math.round((Date.now() - this.state.answerStartTime) / 1000)
            : 0;
        this.submitAnswer(text, null, elapsed);
    }

    /* ============================================================== */
    /*  SKIP QUESTION                                                  */
    /* ============================================================== */
    skipQuestion() {
        if (this.state.isProcessing || this.state.isSpeaking) return;
        this.submitAnswer("I'd like to skip this question.", null, 0);
    }

    /* ============================================================== */
    /*  UI HELPERS                                                     */
    /* ============================================================== */
    updateQuestionCounter() {
        /* no-op: question counter removed — flow is dynamic */
    }

    setCaption(text) {
        if (this.dom.liveCaption) {
            this.dom.liveCaption.textContent = text || '';
            this.dom.liveCaption.classList.toggle('hidden', !text);
        }
    }

    /**
     * Show Priya's spoken text as a subtitle overlay on the avatar panel.
     */
    showSubtitle(text) {
        const el = this.dom.avatarSubtitle;
        if (!el) return;
        el.textContent = text;
        el.style.display = 'block';
        void el.offsetHeight; // force reflow for CSS transition
        el.style.opacity = '1';
    }

    /**
     * Fade out and hide the subtitle overlay.
     */
    hideSubtitle(delay = 1500) {
        const el = this.dom.avatarSubtitle;
        if (!el) return;
        setTimeout(() => {
            el.style.opacity = '0';
            setTimeout(() => {
                el.style.display = 'none';
                el.textContent = '';
            }, 350);
        }, delay);
    }

    disableControls(disabled) {
        [
            this.dom.micBtn,
            this.dom.typeBtn,
            this.dom.skipBtn,
            this.dom.submitCodeBtn,
        ].forEach((btn) => {
            if (btn) {
                btn.disabled = disabled;
                btn.classList.toggle('opacity-50', disabled);
                btn.classList.toggle('pointer-events-none', disabled);
            }
        });
    }

    sleep(ms) {
        return new Promise((resolve) => setTimeout(resolve, ms));
    }

    /* ============================================================== */
    /*  CLEANUP                                                        */
    /* ============================================================== */
    cleanup() {
        this.timer.stop();
        this.avatar.destroy();
        this.audio.destroy();
        this.webcam.destroy();
        this.stopMicLevelAnimation();
    }
}

/* InterviewRoom is instantiated by session_room.html inline script */
