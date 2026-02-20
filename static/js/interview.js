/**
 * InterviewEngine — LevelUpX AI Mock Interview Client
 *
 * Handles: Web Speech API (STT/TTS), avatar animation, Monaco code editor,
 * transcript management, timer, and API communication.
 */
class InterviewEngine {
    constructor() {
        // DOM refs
        this.app = document.getElementById('interview-app');
        this.sessionId = parseInt(this.app.dataset.sessionId);
        this.durationMinutes = parseInt(this.app.dataset.duration);
        this.interviewType = this.app.dataset.interviewType;

        this.transcript = document.getElementById('transcript');
        this.timerText = document.getElementById('timer-text');
        this.qCounterText = document.getElementById('q-counter-text');
        this.micBtn = document.getElementById('mic-btn');
        this.micStatus = document.getElementById('mic-status');
        this.textInput = document.getElementById('text-input');
        this.aiStatusText = document.getElementById('ai-status-text');
        this.speakingIndicator = document.getElementById('speaking-indicator');
        this.codeEditorPanel = document.getElementById('code-editor-panel');

        // State
        this.questionNumber = 0;
        this.totalExpected = 0;
        this.isRecording = false;
        this.isProcessing = false;
        this.isSpeaking = false;
        this.isFinalQuestion = false;
        this.currentRequiresCode = false;
        this.answerStartTime = null;
        this.interimTranscript = '';
        this.finalTranscript = '';

        // Speech recognition
        this.recognition = null;
        this.synthesis = window.speechSynthesis;
        this.preferredVoice = null;

        // Monaco editor
        this.monacoEditor = null;
        this.monacoReady = false;

        // Timer
        this.timerSeconds = this.durationMinutes * 60;
        this.timerInterval = null;

        this.init();
    }

    async init() {
        this.initSpeechRecognition();
        this.selectVoice();
        this.startTimer();
        await this.loadSession();
    }

    // -----------------------------------------------------------------------
    // Load existing session data (for resume after refresh)
    // -----------------------------------------------------------------------
    async loadSession() {
        try {
            const resp = await fetch(`/api/interview/session/${this.sessionId}`);
            if (!resp.ok) return;
            const data = await resp.json();

            this.totalExpected = (data.session && data.session.total_expected) || 8;

            // Replay existing exchanges into transcript
            const exchanges = data.exchanges || [];
            for (const ex of exchanges) {
                this.questionNumber = ex.sequence;
                this.addMessage('interviewer', ex.question_text);
                if (ex.answer_text) {
                    this.addMessage('candidate', ex.answer_text);
                    if (ex.code_text) {
                        this.addMessage('candidate', '```\n' + ex.code_text + '\n```');
                    }
                }
            }

            this.updateQuestionCounter();

            // Check if last exchange needs an answer
            const lastEx = exchanges[exchanges.length - 1];
            if (lastEx && !lastEx.answer_text) {
                // Speak the last question
                this.setStatus('Interviewer is speaking...');
                this.speak(lastEx.question_text);
                this.currentRequiresCode = lastEx.requires_code || false;
                if (this.currentRequiresCode) this.showCodeEditor(lastEx.code_language);
            } else if (exchanges.length === 0) {
                // Fresh session — wait for first question
                this.setStatus('Starting interview...');
            }
        } catch (err) {
            console.error('Failed to load session:', err);
        }
    }

    // -----------------------------------------------------------------------
    // Timer
    // -----------------------------------------------------------------------
    startTimer() {
        this.timerInterval = setInterval(() => {
            if (this.timerSeconds <= 0) {
                clearInterval(this.timerInterval);
                this.endInterview();
                return;
            }
            this.timerSeconds--;
            const m = Math.floor(this.timerSeconds / 60);
            const s = this.timerSeconds % 60;
            this.timerText.textContent = `${m}:${s.toString().padStart(2, '0')}`;

            // Warn at 2 minutes
            if (this.timerSeconds === 120) {
                this.timerText.classList.add('text-amber-600');
            }
            if (this.timerSeconds <= 60) {
                this.timerText.classList.remove('text-amber-600');
                this.timerText.classList.add('text-red-600');
            }
        }, 1000);
    }

    updateQuestionCounter() {
        this.qCounterText.textContent = `Q${this.questionNumber}/${this.totalExpected}`;
    }

    setStatus(text) {
        this.aiStatusText.textContent = text;
    }

    // -----------------------------------------------------------------------
    // Speech Recognition (STT)
    // -----------------------------------------------------------------------
    initSpeechRecognition() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            this.micStatus.textContent = 'Speech not supported — type instead';
            this.micBtn.classList.add('opacity-50');
            return;
        }

        this.recognition = new SpeechRecognition();
        this.recognition.continuous = true;
        this.recognition.interimResults = true;
        this.recognition.lang = 'en-US';

        this.recognition.onresult = (event) => {
            let interim = '';
            let final = '';
            for (let i = event.resultIndex; i < event.results.length; i++) {
                const t = event.results[i][0].transcript;
                if (event.results[i].isFinal) {
                    final += t + ' ';
                } else {
                    interim += t;
                }
            }
            if (final) this.finalTranscript += final;
            this.interimTranscript = interim;

            // Show live transcription
            const liveEl = document.getElementById('live-transcription');
            if (liveEl) {
                liveEl.textContent = this.finalTranscript + this.interimTranscript;
            }
        };

        this.recognition.onerror = (event) => {
            if (event.error === 'no-speech' || event.error === 'aborted') return;
            console.error('Speech error:', event.error);
            this.stopRecording();
        };

        this.recognition.onend = () => {
            // Auto-restart if still recording
            if (this.isRecording) {
                try { this.recognition.start(); } catch (e) { /* ignore */ }
            }
        };
    }

    selectVoice() {
        const loadVoices = () => {
            const voices = this.synthesis.getVoices();
            // Prefer natural/enhanced English voices
            this.preferredVoice =
                voices.find(v => v.name.includes('Google') && v.lang.startsWith('en')) ||
                voices.find(v => v.lang.startsWith('en-') && v.name.includes('Natural')) ||
                voices.find(v => v.lang.startsWith('en-US')) ||
                voices.find(v => v.lang.startsWith('en')) ||
                null;
        };
        loadVoices();
        if (this.synthesis.onvoiceschanged !== undefined) {
            this.synthesis.onvoiceschanged = loadVoices;
        }
    }

    toggleMic() {
        if (this.isProcessing || this.isSpeaking) return;
        if (this.isRecording) {
            this.stopRecording();
            this.submitVoiceAnswer();
        } else {
            this.startRecording();
        }
    }

    startRecording() {
        if (!this.recognition || this.isProcessing || this.isSpeaking) return;

        this.finalTranscript = '';
        this.interimTranscript = '';
        this.answerStartTime = Date.now();
        this.isRecording = true;

        this.micBtn.classList.add('recording');
        this.micStatus.textContent = 'Listening... Click to stop';
        this.setStatus('Listening to your answer...');

        // Add live transcription bubble
        this.addLiveTranscription();

        try {
            this.recognition.start();
        } catch (e) {
            // Already started
        }
    }

    stopRecording() {
        this.isRecording = false;
        this.micBtn.classList.remove('recording');
        this.micStatus.textContent = 'Click to speak';

        if (this.recognition) {
            try { this.recognition.stop(); } catch (e) { /* ignore */ }
        }

        // Remove live transcription bubble
        const liveEl = document.getElementById('live-transcription-wrapper');
        if (liveEl) liveEl.remove();
    }

    addLiveTranscription() {
        const existing = document.getElementById('live-transcription-wrapper');
        if (existing) existing.remove();

        const wrapper = document.createElement('div');
        wrapper.id = 'live-transcription-wrapper';
        wrapper.className = 'flex justify-end';
        wrapper.innerHTML = `
            <div class="max-w-[75%] bg-brand-50 border border-brand-100 rounded-2xl rounded-br-sm px-4 py-2.5">
                <p id="live-transcription" class="text-sm text-brand-700 italic min-h-[1.2em]">Listening...</p>
            </div>`;
        this.transcript.appendChild(wrapper);
        this.scrollTranscript();
    }

    // -----------------------------------------------------------------------
    // Text-to-Speech (TTS)
    // -----------------------------------------------------------------------
    speak(text) {
        if (!this.synthesis) return;

        // Cancel any ongoing speech
        this.synthesis.cancel();

        const utter = new SpeechSynthesisUtterance(text);
        utter.rate = 0.95;
        utter.pitch = 1.0;
        utter.volume = 1.0;
        if (this.preferredVoice) utter.voice = this.preferredVoice;

        utter.onstart = () => {
            this.isSpeaking = true;
            this.speakingIndicator.classList.remove('hidden');
            this.setStatus('Interviewer is speaking...');
        };

        utter.onend = () => {
            this.isSpeaking = false;
            this.speakingIndicator.classList.add('hidden');
            this.setStatus('Your turn — click mic or type');
        };

        utter.onerror = () => {
            this.isSpeaking = false;
            this.speakingIndicator.classList.add('hidden');
            this.setStatus('Your turn — click mic or type');
        };

        this.synthesis.speak(utter);
    }

    // -----------------------------------------------------------------------
    // Transcript Messages
    // -----------------------------------------------------------------------
    addMessage(role, text) {
        const wrapper = document.createElement('div');
        wrapper.className = role === 'interviewer' ? 'flex justify-start' : 'flex justify-end';

        const isCode = text.startsWith('```');
        const displayText = isCode
            ? `<pre class="bg-slate-900 text-emerald-300 p-3 rounded-lg text-xs overflow-x-auto mt-1"><code>${this.escapeHtml(text.replace(/```\n?/g, ''))}</code></pre>`
            : this.escapeHtml(text);

        if (role === 'interviewer') {
            wrapper.innerHTML = `
                <div class="flex gap-2.5 max-w-[80%]">
                    <div class="w-7 h-7 rounded-full bg-gradient-to-br from-brand-500 to-indigo-600 flex items-center justify-center text-white text-[10px] font-bold flex-shrink-0 mt-1">A</div>
                    <div class="bg-slate-50 border border-slate-100 rounded-2xl rounded-tl-sm px-4 py-2.5">
                        <p class="text-sm text-slate-700 leading-relaxed">${displayText}</p>
                    </div>
                </div>`;
        } else {
            wrapper.innerHTML = `
                <div class="max-w-[75%] bg-brand-500 text-white rounded-2xl rounded-br-sm px-4 py-2.5">
                    <p class="text-sm leading-relaxed">${displayText}</p>
                </div>`;
        }

        this.transcript.appendChild(wrapper);
        this.scrollTranscript();
    }

    addTypingIndicator() {
        const existing = document.getElementById('typing-indicator');
        if (existing) return;

        const wrapper = document.createElement('div');
        wrapper.id = 'typing-indicator';
        wrapper.className = 'flex justify-start';
        wrapper.innerHTML = `
            <div class="flex gap-2.5">
                <div class="w-7 h-7 rounded-full bg-gradient-to-br from-brand-500 to-indigo-600 flex items-center justify-center text-white text-[10px] font-bold flex-shrink-0 mt-1">A</div>
                <div class="bg-slate-50 border border-slate-100 rounded-2xl rounded-tl-sm px-4 py-3">
                    <div class="typing-dots"><span></span><span></span><span></span></div>
                </div>
            </div>`;
        this.transcript.appendChild(wrapper);
        this.scrollTranscript();
    }

    removeTypingIndicator() {
        const el = document.getElementById('typing-indicator');
        if (el) el.remove();
    }

    scrollTranscript() {
        this.transcript.scrollTop = this.transcript.scrollHeight;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // -----------------------------------------------------------------------
    // Code Editor (Monaco)
    // -----------------------------------------------------------------------
    showCodeEditor(language) {
        this.currentRequiresCode = true;
        this.codeEditorPanel.classList.remove('hidden');

        // Map language
        const langMap = { python: 'python', javascript: 'javascript', java: 'java', cpp: 'cpp', go: 'go' };
        const monacoLang = langMap[language] || 'python';

        if (this.monacoEditor) {
            // Already loaded — just update language
            monaco.editor.setModelLanguage(this.monacoEditor.getModel(), monacoLang);
            this.monacoEditor.setValue('');
            return;
        }

        // Load Monaco
        require.config({ paths: { vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs' } });
        require(['vs/editor/editor.main'], () => {
            this.monacoEditor = monaco.editor.create(document.getElementById('monaco-container'), {
                value: '',
                language: monacoLang,
                theme: 'vs-dark',
                minimap: { enabled: false },
                fontSize: 13,
                lineNumbers: 'on',
                scrollBeyondLastLine: false,
                automaticLayout: true,
                padding: { top: 10 },
            });
            this.monacoReady = true;
        });

        // Language switch handler
        document.getElementById('code-language').value = language || 'python';
        document.getElementById('code-language').onchange = (e) => {
            if (this.monacoEditor) {
                monaco.editor.setModelLanguage(this.monacoEditor.getModel(), e.target.value);
            }
        };
    }

    hideCodeEditor() {
        this.currentRequiresCode = false;
        this.codeEditorPanel.classList.add('hidden');
    }

    // -----------------------------------------------------------------------
    // Submit Answer
    // -----------------------------------------------------------------------
    async submitVoiceAnswer() {
        const answer = this.finalTranscript.trim();
        if (!answer) {
            this.setStatus('No speech detected — try again or type');
            return;
        }
        await this.submitAnswer(answer);
    }

    async submitTextAnswer() {
        const answer = this.textInput.value.trim();
        if (!answer) return;
        this.textInput.value = '';
        await this.submitAnswer(answer);
    }

    async submitCode() {
        if (!this.monacoEditor) return;
        const code = this.monacoEditor.getValue().trim();
        if (!code) return;

        // Get any text answer too
        const textAnswer = this.finalTranscript.trim() || this.textInput.value.trim() || 'Here is my code solution.';
        this.textInput.value = '';

        await this.submitAnswer(textAnswer, code);
    }

    async submitAnswer(answerText, codeText = null) {
        if (this.isProcessing) return;
        this.isProcessing = true;

        const duration = this.answerStartTime
            ? Math.round((Date.now() - this.answerStartTime) / 1000)
            : 0;
        this.answerStartTime = null;

        // Add candidate message to transcript
        this.addMessage('candidate', answerText);
        if (codeText) {
            this.addMessage('candidate', '```\n' + codeText + '\n```');
        }

        // Show thinking indicator
        this.addTypingIndicator();
        this.setStatus('AI is thinking...');

        try {
            const resp = await fetch('/api/interview/answer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: this.sessionId,
                    answer_text: answerText,
                    code_text: codeText,
                    answer_duration_seconds: duration,
                }),
            });

            this.removeTypingIndicator();

            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                this.setStatus(err.error || 'Error — please try again');
                this.isProcessing = false;
                return;
            }

            const data = await resp.json();

            // Check if interview ended
            if (data.interview_ended) {
                window.location.href = `/career-services/mock-interviews/feedback/${this.sessionId}`;
                return;
            }

            // Update state
            this.questionNumber = data.question_number || (this.questionNumber + 1);
            this.totalExpected = data.total_expected || this.totalExpected;
            this.isFinalQuestion = data.is_final_question || false;
            this.updateQuestionCounter();

            // Add interviewer message
            this.addMessage('interviewer', data.interviewer_message);

            // Handle code editor
            if (data.requires_code) {
                this.showCodeEditor(data.code_language || 'python');
            } else {
                this.hideCodeEditor();
            }

            // Speak the question
            this.speak(data.interviewer_message);

        } catch (err) {
            this.removeTypingIndicator();
            this.setStatus('Network error — please try again');
            console.error('Submit answer error:', err);
        }

        this.isProcessing = false;
        this.finalTranscript = '';
        this.interimTranscript = '';
    }

    // -----------------------------------------------------------------------
    // End Interview
    // -----------------------------------------------------------------------
    async endInterview() {
        if (this.isProcessing) return;

        const endBtn = document.getElementById('end-btn');
        endBtn.disabled = true;
        endBtn.innerHTML = '<svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path></svg> Generating Feedback...';
        this.setStatus('Generating detailed feedback report...');

        // Stop timer, mic, speech
        clearInterval(this.timerInterval);
        this.stopRecording();
        this.synthesis.cancel();

        try {
            const resp = await fetch('/api/interview/end', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: this.sessionId }),
            });

            if (resp.ok) {
                const data = await resp.json();
                window.location.href = data.redirect_url || `/career-services/mock-interviews/feedback/${this.sessionId}`;
            } else {
                this.setStatus('Error ending interview — please try again');
                endBtn.disabled = false;
                endBtn.innerHTML = '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 10a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z"/></svg> End Interview';
            }
        } catch (err) {
            console.error('End interview error:', err);
            this.setStatus('Network error — please try again');
            endBtn.disabled = false;
        }
    }
}
