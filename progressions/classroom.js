(function () {
    const role = document.body.dataset.role;
    const params = new URLSearchParams(window.location.search);
    const adjectives = ["bright", "steady", "quick", "clear", "lively", "calm", "sharp", "warm"];
    const nouns = ["pulse", "cadence", "chord", "voice", "meter", "note", "phrase", "tone"];

    const state = {
        network: null,
        room: "",
        name: randomName(role === "teacher" ? "teacher" : role === "answers" ? "answers" : "student"),
        options: [],
        correctAnswer: "",
        pendingCorrectAnswer: "",
        selectedAnswer: "",
        submittedAnswer: "",
        round: 0,
        lastRound: 0,
        studentEvaluations: new Map(),
        students: new Map(),
        exerciseHistory: new Map(),
        cumulativeSummary: null,
        syncTimer: null,
    };

    function randomName(prefix) {
        const adjective = adjectives[Math.floor(Math.random() * adjectives.length)];
        const noun = nouns[Math.floor(Math.random() * nouns.length)];
        const number = Math.floor(Math.random() * 900 + 100);
        return `${prefix}-${adjective}-${noun}-${number}`;
    }

    function byId(id) {
        return document.getElementById(id);
    }

    function uniqueOptionsFromText(text) {
        return Array.from(
            new Set(
                text
                    .split("\n")
                    .map((line) => line.trim())
                    .filter(Boolean),
            ),
        );
    }

    function setStatus(text, connected) {
        const status = byId("connection-status");
        status.textContent = text;
        status.classList.toggle("connected", Boolean(connected));
    }

    function broadcast(message) {
        if (!state.network) return;
        state.network.broadcast(message);
    }

    function sendState() {
        if (role !== "teacher") return;
        snapshotCurrentExercise();
        broadcast({
            type: "progression-state",
            options: state.options,
            correctAnswer: state.correctAnswer,
            round: state.round,
            cumulativeSummary: getCumulativeSummary(),
        });
    }

    function connect() {
        const room = byId("room-id").value.trim();
        const name = byId("user-name").value.trim();
        if (!room || !name || typeof SimpleP2P === "undefined") return;

        state.room = room;
        state.name = name;
        state.network = new SimpleP2P(room, name);
        setStatus("Connecting", false);

        state.network.onConnect = () => {
            setStatus("Online", true);
            byId("connect-room").disabled = true;
            byId("disconnect-room").disabled = false;
            byId("room-id").disabled = true;

            if (role === "teacher") {
                byId("send-progressions").disabled = false;
                byId("correct-answer").disabled = true;
                byId("reset-round").disabled = false;
                updateOptionsFromInput();
                sendState();
                state.syncTimer = window.setInterval(sendState, 1800);
            } else if (role === "student") {
                announceStudent();
                state.syncTimer = window.setInterval(announceStudent, 1500);
                byId("answer-status").textContent = "Connected. Waiting for the teacher.";
            } else if (role === "answers") {
                renderAnswerStats();
            }
        };

        state.network.onDisconnect = () => {
            setStatus("Offline", false);
            byId("connect-room").disabled = false;
            byId("disconnect-room").disabled = true;
            byId("room-id").disabled = false;
            window.clearInterval(state.syncTimer);
            state.syncTimer = null;
            state.network = null;
            if (role === "teacher") {
                byId("send-progressions").disabled = true;
                byId("correct-answer").disabled = true;
                byId("reset-round").disabled = true;
                state.students.clear();
                renderTeacherStats();
            }
        };

        state.network.onPeerJoin = (peerId, peerName) => {
            if (role === "teacher") {
                renderTeacherStats();
                window.setTimeout(sendState, 600);
            }
        };

        state.network.onPeerLeave = (peerId) => {
            if (role === "teacher") {
                state.students.delete(peerId);
                renderTeacherStats();
            } else if (role === "answers") {
                state.students.delete(peerId);
                renderAnswerStats();
            }
        };

        state.network.onMessage = (peerId, data) => {
            if (!data || typeof data !== "object") return;
            if (role === "teacher") handleTeacherMessage(peerId, data);
            if (role === "student") handleStudentMessage(data);
            if (role === "answers") handleAnswersMessage(peerId, data);
        };

        state.network.onError = (error) => {
            console.error(error);
            setStatus("Error", false);
        };

        state.network.connect();
    }

    function disconnect() {
        state.network?.disconnect();
    }

    function ensureStudent(peerId, fallbackName) {
        if (!state.students.has(peerId)) {
            state.students.set(peerId, {
                id: peerId,
                name: fallbackName || "Student",
                choice: "",
                updatedAt: null,
            });
        }
        return state.students.get(peerId);
    }

    function handleTeacherMessage(peerId, data) {
        if (data.type === "student-hello") {
            const student = ensureStudent(peerId, data.name);
            student.name = data.name || student.name;
            renderTeacherStats();
            sendState();
        }

        if (data.type === "student-choice") {
            const student = ensureStudent(peerId, data.name);
            student.name = data.name || student.name;
            student.choice = data.choice || "";
            student.updatedAt = Date.now();
            renderTeacherStats();
        }
    }

    function handleStudentMessage(data) {
        if (data.type !== "progression-state") return;
        state.options = Array.isArray(data.options) ? data.options : [];
        state.correctAnswer = data.correctAnswer || "";
        const incomingRound = Number(data.round || 0);
        if (incomingRound !== state.lastRound) {
            state.lastRound = incomingRound;
            state.selectedAnswer = "";
            state.submittedAnswer = "";
        }
        if (!state.options.includes(state.selectedAnswer)) {
            state.selectedAnswer = "";
        }
        if (!state.options.includes(state.submittedAnswer)) {
            state.submittedAnswer = "";
        }
        evaluateStudentAnswer();
        renderStudentOptions();
    }

    function handleAnswersMessage(peerId, data) {
        if (data.type === "progression-state") {
            state.options = Array.isArray(data.options) ? data.options : [];
            state.correctAnswer = data.correctAnswer || "";
            state.cumulativeSummary = data.cumulativeSummary || null;
            const incomingRound = Number(data.round || 0);
            state.round = incomingRound;
            if (incomingRound !== state.lastRound) {
                state.lastRound = incomingRound;
                state.students.forEach((student) => {
                    student.choice = "";
                    student.updatedAt = null;
                });
            }
            renderAnswerStats();
            return;
        }

        if (data.type === "student-hello") {
            const student = ensureStudent(peerId, data.name);
            student.name = data.name || student.name;
            renderAnswerStats();
        }

        if (data.type === "student-choice") {
            const student = ensureStudent(peerId, data.name);
            student.name = data.name || student.name;
            student.choice = data.choice || "";
            student.updatedAt = Date.now();
            renderAnswerStats();
        }
    }

    function announceStudent() {
        broadcast({
            type: "student-hello",
            name: state.name,
        });
        if (state.submittedAnswer) sendStudentChoice(state.submittedAnswer);
    }

    function sendStudentChoice(choice) {
        state.submittedAnswer = choice;
        broadcast({
            type: "student-choice",
            name: state.name,
            choice,
        });
        evaluateStudentAnswer();
        renderStudentOptions();
    }

    function evaluateStudentAnswer() {
        if (role !== "student" || !state.correctAnswer || !state.submittedAnswer) return;
        state.studentEvaluations.set(state.lastRound, state.submittedAnswer === state.correctAnswer);
        renderStudentScore();
    }

    function renderStudentScore() {
        if (role !== "student") return;
        const rightEl = byId("student-right-count");
        const wrongEl = byId("student-wrong-count");
        if (!rightEl || !wrongEl) return;

        const evaluations = Array.from(state.studentEvaluations.values());
        rightEl.textContent = String(evaluations.filter(Boolean).length);
        wrongEl.textContent = String(evaluations.filter((value) => !value).length);
    }

    function updateOptionsFromInput() {
        state.options = uniqueOptionsFromText(byId("progression-input").value);
        if (!state.options.includes(state.correctAnswer)) {
            state.correctAnswer = "";
        }
        if (!state.options.includes(state.pendingCorrectAnswer)) {
            state.pendingCorrectAnswer = "";
        }
        renderTeacherOptions();
        renderCorrectOptions();
        renderTeacherStats();
    }

    function renderTeacherOptions() {
        const container = byId("teacher-options");
        if (!container) return;
        container.innerHTML = "";
        state.options.forEach((option) => {
            const block = document.createElement("button");
            block.type = "button";
            block.className = "progression-block";
            block.textContent = option;
            container.appendChild(block);
        });
    }

    function renderCorrectOptions() {
        const container = byId("correct-options");
        container.innerHTML = "";
        const answerIsLocked = Boolean(state.correctAnswer);
        const correctAnswerButton = byId("correct-answer");
        if (correctAnswerButton) {
            correctAnswerButton.disabled = !answerIsLocked;
        }
        state.options.forEach((option) => {
            const block = document.createElement("button");
            block.type = "button";
            block.disabled = answerIsLocked;
            block.className = [
                "progression-block",
                state.correctAnswer === option ? "selected revealed" : "",
            ]
                .filter(Boolean)
                .join(" ");
            block.textContent = option;
            block.addEventListener("click", () => {
                if (state.correctAnswer) return;
                state.pendingCorrectAnswer = option;
                defineAnswer();
            });
            container.appendChild(block);
        });
    }

    function defineAnswer() {
        if (!state.pendingCorrectAnswer) return;
        state.correctAnswer = state.pendingCorrectAnswer;
        renderCorrectOptions();
        renderTeacherStats();
        sendState();
    }

    function unlockCorrectAnswer() {
        state.correctAnswer = "";
        state.pendingCorrectAnswer = "";
        renderCorrectOptions();
        renderTeacherStats();
        sendState();
    }

    function renderTeacherStats() {
        renderAnswerStats();
    }

    function renderAnswerStats() {
        if (role === "teacher") {
            snapshotCurrentExercise();
        }

        const students = Array.from(state.students.values());
        const answered = students.filter((student) => student.choice);
        const correct = state.correctAnswer
            ? answered.filter((student) => student.choice === state.correctAnswer).length
            : 0;
        const incorrect = state.correctAnswer
            ? answered.filter((student) => student.choice !== state.correctAnswer).length
            : 0;
        const missing = students.length - answered.length;
        const percent = (value) => {
            if (students.length === 0) return "0%";
            return `${Math.round((value / students.length) * 100)}%`;
        };

        byId("student-count").textContent = String(students.length);
        const onlineCount = byId("online-count");
        if (onlineCount) {
            onlineCount.textContent = String(students.length);
        }
        const exerciseCounter = byId("exercise-counter");
        if (exerciseCounter) {
            const totalExercises =
                role === "answers" && state.cumulativeSummary
                    ? state.cumulativeSummary.totalExercises
                    : getTotalExercises();
            exerciseCounter.textContent = `${totalExercises} total exercise${totalExercises === 1 ? "" : "s"}`;
        }
        byId("correct-count").textContent = String(correct);
        byId("incorrect-count").textContent = String(incorrect);
        byId("missing-count").textContent = String(missing);
        byId("student-percent").textContent = students.length === 0 ? "0%" : "100%";
        byId("correct-percent").textContent = percent(correct);
        byId("incorrect-percent").textContent = percent(incorrect);
        byId("missing-percent").textContent = percent(missing);
        renderProgressionSummary(students);

        const list = byId("response-list");
        list.innerHTML = "";
        if (students.length === 0) {
            const empty = document.createElement("p");
            empty.className = "quiet";
            empty.textContent = "No students connected yet.";
            list.appendChild(empty);
            return;
        }

        students
            .sort((a, b) => a.name.localeCompare(b.name))
            .forEach((student) => {
                const row = document.createElement("div");
                const hasAnswer = Boolean(student.choice);
                const isCorrect = state.correctAnswer && student.choice === state.correctAnswer;
                const badgeClass = !hasAnswer ? "" : isCorrect ? "correct" : "incorrect";
                const badgeText = !hasAnswer ? "No answer" : isCorrect ? "Correct" : "Incorrect";

                row.className = "response-row";
                row.innerHTML = `
                    <div class="name"></div>
                    <div class="choice"></div>
                    <div class="badge ${badgeClass}"></div>
                `;
                row.querySelector(".name").textContent = student.name;
                row.querySelector(".choice").textContent = student.choice || "Waiting";
                row.querySelector(".badge").textContent = state.correctAnswer ? badgeText : "Received";
                list.appendChild(row);
            });
    }

    function renderProgressionSummary(students) {
        const container = byId("progression-summary");
        if (!container) return;

        const summary = role === "teacher" ? getCumulativeSummary() : state.cumulativeSummary;
        const rows = summary?.rows || [];
        container.innerHTML = "";
        if (rows.length === 0) {
            const empty = document.createElement("p");
            empty.className = "quiet";
            empty.textContent = "No progression options yet.";
            container.appendChild(empty);
            return;
        }

        rows.forEach((item) => {
            const row = document.createElement("div");
            row.className = "summary-row";
            row.innerHTML = `
                <div class="progression-name"></div>
                <div class="progression-count"></div>
                <div class="summary-split"></div>
                <div class="progression-percent"></div>
            `;

            row.querySelector(".progression-name").textContent = item.option;
            row.querySelector(".progression-count").textContent =
                `${item.exercises} exercise${item.exercises === 1 ? "" : "s"} / ` +
                `${item.selected} selection${item.selected === 1 ? "" : "s"}`;
            row.querySelector(".summary-split").innerHTML = `
                <span class="badge correct">${item.right} right</span>
                <span class="badge incorrect">${item.wrong} wrong</span>
            `;
            const evaluated = item.right + item.wrong;
            row.querySelector(".progression-percent").textContent =
                evaluated === 0 ? "0%" : `${Math.round((item.right / evaluated) * 100)}% right`;

            container.appendChild(row);
        });
    }

    function snapshotCurrentExercise() {
        if (role !== "teacher") return;

        state.exerciseHistory.set(state.round, {
            options: [...state.options],
            correctAnswer: state.correctAnswer,
            answers: Array.from(state.students.values())
                .filter((student) => student.choice)
                .map((student) => ({
                    studentId: student.id,
                    name: student.name,
                    choice: student.choice,
                })),
        });
    }

    function getTotalExercises() {
        return Math.max(state.round + 1, state.exerciseHistory.size || 1);
    }

    function getCumulativeSummary() {
        snapshotCurrentExercise();

        const totals = new Map();
        let totalSelections = 0;

        const ensure = (option) => {
            if (!totals.has(option)) {
                totals.set(option, {
                    option,
                    exercises: 0,
                    selected: 0,
                    right: 0,
                    wrong: 0,
                });
            }
            return totals.get(option);
        };

        for (const exercise of state.exerciseHistory.values()) {
            exercise.options.forEach(ensure);
            if (exercise.correctAnswer) {
                ensure(exercise.correctAnswer).exercises += 1;
            }

            exercise.answers.forEach((answer) => {
                ensure(answer.choice).selected += 1;
                totalSelections += 1;

                if (exercise.correctAnswer) {
                    const correctItem = ensure(exercise.correctAnswer);
                    if (answer.choice === exercise.correctAnswer) {
                        correctItem.right += 1;
                    } else {
                        correctItem.wrong += 1;
                    }
                }
            });
        }

        return {
            totalExercises: getTotalExercises(),
            totalSelections,
            rows: Array.from(totals.values()),
        };
    }

    function renderStudentOptions() {
        const container = byId("student-options");
        container.innerHTML = "";
        const sendButton = byId("send-answer");
        if (sendButton) {
            sendButton.disabled = true;
        }

        if (state.options.length === 0) {
            byId("student-prompt").textContent = "Waiting for progressions";
            byId("answer-status").textContent = state.network
                ? "Connected. Waiting for the teacher."
                : "Join the room to receive the options.";
            return;
        }

        byId("student-prompt").textContent = "What was played";
        const isSubmitted = Boolean(state.submittedAnswer);
        byId("answer-status").textContent = isSubmitted
            ? "Answer sent. Wait for the next exercise to answer again."
            : state.selectedAnswer
              ? "Ready to send."
              : "Tap one block, then send your answer.";
        if (sendButton) {
            sendButton.disabled = !state.selectedAnswer || isSubmitted;
        }

        state.options.forEach((option) => {
            const block = document.createElement("button");
            block.type = "button";
            block.disabled = isSubmitted;
            block.className = [
                "progression-block",
                (state.submittedAnswer || state.selectedAnswer) === option ? "selected" : "",
            ]
                .filter(Boolean)
                .join(" ");
            block.textContent = option;
            block.addEventListener("click", () => {
                if (state.submittedAnswer) return;
                state.selectedAnswer = option;
                renderStudentOptions();
            });
            container.appendChild(block);
        });
    }

    function resetRound() {
        snapshotCurrentExercise();
        state.correctAnswer = "";
        state.pendingCorrectAnswer = "";
        state.round += 1;
        state.students.forEach((student) => {
            student.choice = "";
            student.updatedAt = null;
        });
        renderCorrectOptions();
        renderTeacherStats();
        sendState();
    }

    function updateStudentLink() {
        if (role !== "answers") return;
        const room = byId("room-id").value.trim() || "myclassname";
        const url = new URL("../students/", window.location.href);
        url.searchParams.set("roomid", room);
        const link = url.href;
        byId("student-link").value = link;
        byId("student-room-label").textContent = `Room: ${room}`;
        byId("student-qr").src =
            `https://api.qrserver.com/v1/create-qr-code/?size=360x360&margin=18&data=${encodeURIComponent(link)}`;
    }

    function init() {
        const roomInput = byId("room-id");
        const nameInput = byId("user-name");
        roomInput.value = params.get("roomid") || params.get("room") || "myclassname";
        nameInput.value = params.get("name") || state.name;

        byId("connect-room").addEventListener("click", connect);
        byId("disconnect-room").addEventListener("click", disconnect);

        if (role === "teacher") {
            updateOptionsFromInput();
            renderTeacherStats();
            byId("progression-input").addEventListener("input", () => {
                updateOptionsFromInput();
                sendState();
            });
            byId("send-progressions").addEventListener("click", () => {
                updateOptionsFromInput();
                sendState();
            });
            byId("correct-answer").addEventListener("click", unlockCorrectAnswer);
            byId("reset-round").addEventListener("click", resetRound);
        } else {
            if (role === "student") {
                renderStudentOptions();
                renderStudentScore();
                byId("send-answer").addEventListener("click", () => {
                    if (!state.selectedAnswer || state.submittedAnswer) return;
                    sendStudentChoice(state.selectedAnswer);
                });
            }
            if (role === "answers") {
                updateStudentLink();
                renderAnswerStats();
                roomInput.addEventListener("input", updateStudentLink);
            }
            if (params.has("roomid") || params.has("room")) {
                window.setTimeout(connect, 150);
            }
        }
    }

    init();
})();
