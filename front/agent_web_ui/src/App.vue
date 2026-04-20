<template>
  <div class="app-shell">
    <div v-if="!isLoggedIn" class="login-screen">
      <div class="login-card">
        <div class="login-brand">
          <img src="/its-logo.svg" alt="ITS" class="brand-logo" />
          <div>
            <p class="eyebrow">ITS Assistant</p>
            <h1>Log in to continue</h1>
          </div>
        </div>

        <div class="login-fields">
          <label class="field">
            <span>Username</span>
            <input
              id="username"
              v-model="username"
              type="text"
              placeholder="root1 / root2 / root3"
              @keyup.enter="handleLogin"
            />
          </label>

          <label class="field">
            <span>Password</span>
            <input
              id="password"
              v-model="password"
              type="password"
              placeholder="123456"
              @keyup.enter="handleLogin"
            />
          </label>
        </div>

        <p v-if="loginError" class="login-error">{{ loginError }}</p>

        <button class="primary-button login-submit" @click="handleLogin">Continue</button>

        <div class="login-hint">
          <span>Test accounts: root1, root2, root3</span>
          <span>Password: 123456</span>
        </div>
      </div>
    </div>

    <div v-else class="workspace">
      <aside class="sidebar" :class="{ collapsed: !isSidebarExpanded }">
        <div class="sidebar-top">
          <div class="sidebar-brand">
            <img src="/its-logo.svg" alt="ITS" class="brand-logo small" />
            <div v-if="isSidebarExpanded" class="brand-copy">
              <strong>ITS</strong>
              <span>Multi-agent chat</span>
            </div>
          </div>

          <button
            class="icon-button"
            :title="isSidebarExpanded ? 'Collapse sidebar' : 'Expand sidebar'"
            @click="toggleSidebar"
          >
            {{ isSidebarExpanded ? '‹' : '›' }}
          </button>
        </div>

        <button v-if="isSidebarExpanded" class="new-chat-button" @click="createNewSession">
          <span>+</span>
          <span>New chat</span>
        </button>

        <div v-if="isSidebarExpanded" class="sidebar-section">
          <p class="sidebar-label">Spaces</p>
          <button
            class="nav-pill"
            :class="{ active: selectedNavItem === 'knowledge' }"
            @click="handleKnowledgeBase"
          >
            Knowledge Base
          </button>
          <button
            class="nav-pill"
            :class="{ active: selectedNavItem === 'service' }"
            @click="handleServiceStation"
          >
            Service Station
          </button>
          <button
            class="nav-pill"
            :class="{ active: selectedNavItem === 'network' }"
            @click="handleNetworkSearch"
          >
            Network Search
          </button>
        </div>

        <div v-if="isSidebarExpanded" class="sidebar-section sessions-panel">
          <button class="section-header" @click="toggleSessions">
            <span>Chats</span>
            <span>{{ showSessions ? '−' : '+' }}</span>
          </button>

          <div v-if="showSessions" class="session-list">
            <p v-if="isLoadingSessions" class="sidebar-state">Loading chats...</p>
            <p v-else-if="sessions.length === 0" class="sidebar-state">No chat history yet.</p>

            <button
              v-for="session in sessions"
              :key="session.session_id"
              class="session-item"
              :class="{ active: session.session_id === selectedSessionId }"
              @click="selectSession(session.session_id)"
            >
              <span class="session-title">{{ getSessionPreview(session) }}</span>
              <span class="session-meta">{{ formatSessionTime(session.create_time) }}</span>
            </button>
          </div>
        </div>
      </aside>

      <main class="main-panel">
        <header class="topbar">
          <div class="topbar-copy">
            <p class="eyebrow">ITS Assistant</p>
            <h2>{{ currentViewTitle }}</h2>
          </div>

          <div class="account-area" ref="avatarContainerRef">
            <button class="account-button" @click="toggleUserInfo">
              <span class="account-avatar">{{ currentUserInitial }}</span>
              <span class="account-name">{{ currentUser }}</span>
            </button>

            <div v-if="showUserInfo" class="account-menu">
              <span class="account-menu-user">{{ currentUser }}</span>
              <button class="menu-action" @click="handleLogout">Log out</button>
            </div>
          </div>
        </header>

        <section ref="processContent" class="conversation-scroll">
          <div v-if="chatMessages.length === 0" class="empty-state">
            <div class="empty-mark">✦</div>
            <h3>How can ITS help today?</h3>
            <p>Ask about the knowledge base, services, or start a new troubleshooting conversation.</p>
          </div>

          <div
            v-for="(msg, index) in chatMessages"
            :key="index"
            class="message-row"
            :class="messageClass(msg)"
          >
            <div class="message-avatar">
              <span v-if="msg.type === 'user'">你</span>
              <span v-else-if="msg.type === 'assistant'">AI</span>
              <span v-else>…</span>
            </div>

            <div class="message-body">
              <div
                v-if="msg.type === 'THINKING'"
                class="thinking-header"
                @click="toggleThinking(index)"
              >
                <span>{{ isProcessing && index === chatMessages.length - 1 ? 'Thinking' : 'Reasoning trace' }}</span>
                <span class="thinking-toggle">{{ msg.collapsed ? 'Show' : 'Hide' }}</span>
              </div>

              <div
                v-show="msg.type !== 'THINKING' || !msg.collapsed"
                class="message-card"
                :class="messageCardClass(msg)"
              >
                <div class="markdown-body" v-html="renderMarkdown(msg.content)"></div>
              </div>
            </div>
          </div>
        </section>

        <footer class="composer-wrap">
          <div class="composer">
            <textarea
              ref="textareaRef"
              v-model="userInput"
              class="composer-input"
              placeholder="Message ITS Assistant"
              :disabled="isProcessing"
              @input="adjustTextareaHeight"
              @keydown.enter.exact.prevent="handleSend($event)"
            ></textarea>

            <div class="composer-actions">
              <span class="composer-hint">Enter to send, Shift+Enter for newline</span>
              <button
                class="primary-button send-button"
                :class="{ stop: isProcessing }"
                :disabled="!userInput.trim() && !isProcessing"
                @click="isProcessing ? handleCancel() : handleSend()"
              >
                {{ isProcessing ? 'Stop' : 'Send' }}
              </button>
            </div>
          </div>
        </footer>
      </main>
    </div>
  </div>
</template>

<script>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { marked } from 'marked';

marked.setOptions({
  breaks: true,
  gfm: true
});

const renderMarkdown = (text) => {
  if (!text) return '';
  try {
    return marked.parse(text);
  } catch (error) {
    console.error('Markdown parsing error:', error);
    return text;
  }
};

const VALID_USERS = [
  { username: 'root1', password: '123456', userId: 'root1' },
  { username: 'root2', password: '123456', userId: 'root2' },
  { username: 'root3', password: '123456', userId: 'root3' }
];

export default {
  name: 'App',
  setup() {
    const savedUserId = localStorage.getItem('currentUserId');
    const savedUser = VALID_USERS.find((item) => item.userId === savedUserId);

    const isLoggedIn = ref(Boolean(savedUser));
    const isSidebarExpanded = ref(true);
    const username = ref('');
    const password = ref('');
    const currentUser = ref(savedUser ? savedUser.username : '');
    const loginError = ref('');
    const showUserInfo = ref(false);
    const avatarContainerRef = ref(null);
    const textareaRef = ref(null);

    const userInput = ref('');
    const chatMessages = ref([]);
    const processMessages = ref([]);
    const answerText = ref('');
    const processContent = ref(null);
    const isProcessing = ref(false);
    const selectedNavItem = ref('');
    const sessions = ref([]);
    const selectedSessionId = ref('');
    const isLoadingSessions = ref(false);
    const showSessions = ref(true);

    let reader = null;

    const currentUserInitial = computed(() => (currentUser.value || 'U').slice(0, 1).toUpperCase());

    const currentViewTitle = computed(() => {
      if (selectedNavItem.value === 'knowledge') return 'Knowledge Base';
      if (selectedNavItem.value === 'service') return 'Service Station';
      if (selectedNavItem.value === 'network') return 'Network Search';
      if (selectedSessionId.value) return 'Conversation';
      return 'New conversation';
    });

    const toggleUserInfo = () => {
      showUserInfo.value = !showUserInfo.value;
    };

    const handleClickOutside = (event) => {
      if (showUserInfo.value && avatarContainerRef.value && !avatarContainerRef.value.contains(event.target)) {
        showUserInfo.value = false;
      }
    };

    const adjustTextareaHeight = () => {
      const element = textareaRef.value;
      if (!element) return;
      element.style.height = '0px';
      element.style.height = `${Math.min(element.scrollHeight, 220)}px`;
    };

    const resetConversationState = () => {
      chatMessages.value = [];
      processMessages.value = [];
      answerText.value = '';
      processContent.value = null;
    };

    const handleKnowledgeBase = () => {
      selectedNavItem.value = 'knowledge';
      selectedSessionId.value = '';
      resetConversationState();
    };

    const handleNetworkSearch = () => {
      selectedNavItem.value = 'network';
      selectedSessionId.value = '';
      resetConversationState();
    };

    const handleServiceStation = () => {
      selectedNavItem.value = 'service';
      selectedSessionId.value = '';
      resetConversationState();
    };

    const toggleThinking = (index) => {
      const msg = chatMessages.value[index];
      if (msg && msg.type === 'THINKING') {
        msg.collapsed = !msg.collapsed;
      }
    };

    const toggleSessions = () => {
      showSessions.value = !showSessions.value;
    };

    const handleLogin = () => {
      loginError.value = '';
      const user = VALID_USERS.find(
        (item) => item.username === username.value && item.password === password.value
      );

      if (!user) {
        loginError.value = 'Incorrect username or password';
        return;
      }

      isLoggedIn.value = true;
      currentUser.value = user.username;
      localStorage.setItem('currentUserId', user.userId);
      username.value = '';
      password.value = '';
    };

    const fetchUserSessions = async () => {
      if (!currentUser.value) return;

      isLoadingSessions.value = true;
      try {
        const response = await fetch('http://127.0.0.1:8000/api/user_sessions', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ user_id: currentUser.value })
        });

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        if (data.success && data.sessions) {
          sessions.value = data.sessions;
          if (data.sessions.length > 0 && !selectedSessionId.value) {
            selectSession(data.sessions[0].session_id);
          }
        }
      } catch (error) {
        console.error('Error fetching sessions:', error);
      } finally {
        isLoadingSessions.value = false;
        scrollToBottom();
      }
    };

    const createNewSession = () => {
      const newSessionId = `session_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`;
      const newSession = {
        session_id: newSessionId,
        create_time: new Date().toISOString(),
        memory: [],
        total_messages: 0
      };

      sessions.value.unshift(newSession);
      selectedNavItem.value = '';
      userInput.value = '';
      resetConversationState();
      selectSession(newSessionId);
    };

    const selectSession = (sessionId) => {
      selectedSessionId.value = sessionId;
      selectedNavItem.value = '';
      resetConversationState();

      const session = sessions.value.find((item) => item.session_id === sessionId);
      if (!session || !Array.isArray(session.memory) || session.memory.length === 0) {
        return;
      }

      let lastType = null;
      session.memory.forEach((msg) => {
        if (!msg || !msg.content) return;
        let type = msg.role;
        if (type === 'process') type = 'THINKING';

        if (type === 'THINKING' && lastType === 'THINKING') {
          const lastMsg = chatMessages.value[chatMessages.value.length - 1];
          if (lastMsg) {
            lastMsg.content += `\n${msg.content}`;
          }
        } else {
          chatMessages.value.push({
            type,
            content: msg.content,
            collapsed: false
          });
        }
        lastType = type;
      });

      nextTick(() => {
        scrollToBottom();
      });
    };

    const handleLogout = () => {
      isLoggedIn.value = false;
      currentUser.value = '';
      localStorage.removeItem('currentUserId');
      userInput.value = '';
      sessions.value = [];
      selectedSessionId.value = '';
      selectedNavItem.value = '';
      resetConversationState();
      showUserInfo.value = false;
    };

    const goToLogin = () => {
      handleLogout();
    };

    const processSSEData = (data) => {
      try {
        if (typeof data !== 'string' || !data.startsWith('data:')) return;

        const jsonStr = data.substring(5).trim();
        if (!jsonStr) return;

        const parsedData = JSON.parse(jsonStr);
        let kind;
        let text;

        if (parsedData.content && typeof parsedData.content === 'object') {
          text = parsedData.content.text;
          kind = parsedData.content.kind || parsedData.content.type;
          if (parsedData.status === 'FINISHED' || parsedData.content.contentType === 'sagegpt/finish') {
            return;
          }
        } else if (parsedData.type && parsedData.content) {
          kind = parsedData.type;
          text = parsedData.content;
        }

        if (!kind || !text) return;

        switch (kind) {
          case 'ANSWER':
            stopThinkingAnimation();
            streamTextToAnswer(text);
            break;
          case 'THINKING':
            streamTextToProcess(text);
            break;
          case 'PROCESS':
            streamTextToProcess(`${text}\n`);
            processMessages.value = [...processMessages.value, { type: 'PROCESS', text }];
            scrollToBottom();
            break;
          default:
            streamTextToProcess(`${text}\n`);
            break;
        }
      } catch (error) {
        console.error('Error processing SSE data:', error);
      }
    };

    const handleSend = async (event) => {
      if (event) {
        event.preventDefault();
      }
      if (!userInput.value.trim()) return;

      const userId = localStorage.getItem('currentUserId');
      if (!userId) {
        isLoggedIn.value = false;
        return;
      }

      isProcessing.value = true;
      chatMessages.value.forEach((msg) => {
        if (msg.type === 'THINKING') {
          msg.collapsed = true;
        }
      });

      processMessages.value = [];

      const question = userInput.value.trim();
      chatMessages.value.push({
        type: 'user',
        content: question
      });

      const userMessage = `<div class="user-message">${question}</div>\n\n`;
      if (selectedSessionId.value && answerText.value) {
        answerText.value += userMessage;
      } else {
        answerText.value = userMessage;
      }

      const finalUserId = userId || currentUser.value;
      scrollToBottom();

      const requestData = {
        query: question,
        context: {
          user_id: finalUserId,
          session_id: selectedSessionId.value || ''
        }
      };

      try {
        const response = await fetch('http://127.0.0.1:8000/api/query', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify(requestData)
        });

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }

        reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();

          if (done) {
            if (buffer.trim()) {
              processSSEData(buffer);
              buffer = '';
            }
            break;
          }

          const chunk = decoder.decode(value, { stream: true });
          buffer += chunk;
          const lines = buffer.split('\n');

          for (let i = 0; i < lines.length - 1; i += 1) {
            const line = lines[i];
            if (line.trim()) {
              processSSEData(line);
            }
          }

          buffer = lines[lines.length - 1];
        }
      } catch (error) {
        if (!error.name || error.name !== 'AbortError') {
          const errorMsg = `Request failed: ${error.message}`;
          streamTextToProcess(`${errorMsg}\n`);
          processMessages.value.push({
            type: 'PROCESS',
            text: errorMsg
          });
          console.error('Error:', error);
        }
      } finally {
        isProcessing.value = false;
        reader = null;
        scrollToBottom();
        fetchUserSessions();
      }

      userInput.value = '';
      nextTick(() => {
        adjustTextareaHeight();
      });
    };

    const handleCancel = () => {
      if (reader) {
        reader.cancel();
        reader = null;
      }
      isProcessing.value = false;
      stopThinkingAnimation();
      streamTextToProcess('Request canceled\n');
      processMessages.value.push({
        type: 'PROCESS',
        text: 'Request canceled'
      });
    };

    const streamTextToAnswer = (text) => {
      const lastMsg = chatMessages.value[chatMessages.value.length - 1];
      if ((!text || !text.trim()) && lastMsg && lastMsg.type !== 'assistant') {
        return;
      }

      const normalizedText = text.replace(/ +/g, ' ').replace(/\n+/g, '\n');

      if (lastMsg && lastMsg.type === 'assistant') {
        lastMsg.content += normalizedText;
      } else {
        chatMessages.value.push({ type: 'assistant', content: normalizedText });
      }
      chatMessages.value = [...chatMessages.value];
      answerText.value += normalizedText;
      scrollToBottom();
    };

    const streamTextToProcess = (text) => {
      const lastMsg = chatMessages.value[chatMessages.value.length - 1];
      if (lastMsg && lastMsg.type === 'THINKING') {
        lastMsg.content += text;
      } else {
        chatMessages.value.push({
          type: 'THINKING',
          content: text,
          collapsed: false
        });
      }
      chatMessages.value = [...chatMessages.value];

      const lastProcessMsg = processMessages.value[processMessages.value.length - 1];
      if (lastProcessMsg && lastProcessMsg.type === 'THINKING') {
        lastProcessMsg.text += text;
        processMessages.value = [...processMessages.value];
      } else {
        processMessages.value = [...processMessages.value, { type: 'THINKING', text }];
      }
      scrollToBottom();
    };

    const startThinkingAnimation = () => {};
    const stopThinkingAnimation = () => {};

    const handleResponseData = (data) => {
      if (data.type === 'ANSWER') {
        stopThinkingAnimation();
        streamTextToAnswer(data.content);
      } else if (data.type === 'THINKING') {
        streamTextToProcess(data.content);
      } else if (data.type === 'PROCESS') {
        stopThinkingAnimation();
        processMessages.value.push({ type: 'PROCESS', text: data.content });
        scrollToBottom();
      }
    };

    const scrollToBottom = () => {
      setTimeout(() => {
        const chatContainer = processContent.value;
        if (chatContainer) {
          chatContainer.scrollTop = chatContainer.scrollHeight;
        }
      }, 0);
    };

    const handleKeyDown = (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key === 'k') {
        event.preventDefault();
        createNewSession();
      }
    };

    const toggleSidebar = () => {
      isSidebarExpanded.value = !isSidebarExpanded.value;
    };

    const stripHtml = (text = '') =>
      text
        .replace(/<[^>]*>/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();

    const getSessionPreview = (session) => {
      const firstContent = session?.memory?.[0]?.content || 'New chat';
      return stripHtml(firstContent).slice(0, 48) || 'New chat';
    };

    const formatSessionTime = (time) => {
      if (!time) return '';
      const date = new Date(time);
      if (Number.isNaN(date.getTime())) return '';
      return date.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric'
      });
    };

    const messageClass = (msg) => {
      if (msg.type === 'THINKING') return 'thinking';
      if (msg.type === 'user') return 'user';
      return 'assistant';
    };

    const messageCardClass = (msg) => {
      if (msg.type === 'THINKING') return 'thinking-card';
      if (msg.type === 'user') return 'user-card';
      return 'assistant-card';
    };

    watch(isLoggedIn, (newVal) => {
      if (newVal && currentUser.value) {
        fetchUserSessions();
      }
    });

    onMounted(() => {
      document.addEventListener('click', handleClickOutside);
      document.addEventListener('keydown', handleKeyDown);
      nextTick(() => {
        adjustTextareaHeight();
      });

      if (isLoggedIn.value && currentUser.value) {
        fetchUserSessions();
        nextTick(() => {
          scrollToBottom();
        });
      }
    });

    onUnmounted(() => {
      document.removeEventListener('click', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    });

    return {
      answerText,
      avatarContainerRef,
      chatMessages,
      createNewSession,
      currentUser,
      currentUserInitial,
      currentViewTitle,
      fetchUserSessions,
      formatSessionTime,
      getSessionPreview,
      goToLogin,
      handleCancel,
      handleKnowledgeBase,
      handleLogin,
      handleLogout,
      handleNetworkSearch,
      handleResponseData,
      handleSend,
      handleServiceStation,
      isLoadingSessions,
      isLoggedIn,
      isProcessing,
      isSidebarExpanded,
      loginError,
      messageCardClass,
      messageClass,
      password,
      processContent,
      processMessages,
      renderMarkdown,
      selectSession,
      selectedNavItem,
      selectedSessionId,
      sessions,
      showSessions,
      showUserInfo,
      textareaRef,
      toggleSessions,
      toggleSidebar,
      toggleThinking,
      toggleUserInfo,
      userInput,
      username,
      adjustTextareaHeight
    };
  }
};
</script>

<style scoped>
.app-shell {
  width: 100%;
  min-height: 100vh;
}

.login-screen {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 32px;
}

.login-card {
  width: min(100%, 420px);
  padding: 32px;
  border: 1px solid var(--border-strong);
  border-radius: 28px;
  background: rgba(22, 24, 29, 0.86);
  box-shadow: 0 40px 120px rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(20px);
}

.login-brand {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 28px;
}

.brand-logo {
  width: 52px;
  height: 52px;
  border-radius: 14px;
}

.brand-logo.small {
  width: 36px;
  height: 36px;
}

.eyebrow {
  margin: 0 0 6px;
  color: var(--text-tertiary);
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.login-card h1,
.topbar-copy h2,
.empty-state h3 {
  margin: 0;
  font-weight: 600;
  color: var(--text-primary);
}

.login-fields {
  display: grid;
  gap: 14px;
}

.field {
  display: grid;
  gap: 8px;
}

.field span {
  font-size: 13px;
  color: var(--text-secondary);
}

.field input {
  width: 100%;
  height: 48px;
  padding: 0 14px;
  border: 1px solid var(--border-strong);
  border-radius: 14px;
  background: var(--surface-2);
  color: var(--text-primary);
  font: inherit;
  box-sizing: border-box;
}

.field input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 4px rgba(25, 195, 125, 0.14);
}

.login-error {
  margin: 16px 0 0;
  color: #ff8d8d;
  font-size: 14px;
}

.login-submit {
  width: 100%;
  margin-top: 20px;
}

.login-hint {
  margin-top: 18px;
  display: grid;
  gap: 4px;
  color: var(--text-tertiary);
  font-size: 13px;
}

.workspace {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  min-height: 100vh;
}

.sidebar {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 10px;
  border-right: 1px solid var(--border-soft);
  background: rgba(18, 20, 24, 0.88);
  transition: grid-template-columns 0.2s ease, width 0.2s ease;
}

.sidebar.collapsed {
  width: 84px;
  padding-inline: 8px;
}

.sidebar-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.brand-copy {
  display: grid;
  min-width: 0;
}

.brand-copy strong {
  color: var(--text-primary);
  font-size: 15px;
}

.brand-copy span {
  color: var(--text-tertiary);
  font-size: 12px;
}

.icon-button,
.account-button,
.menu-action,
.session-item,
.nav-pill,
.section-header,
.new-chat-button,
.primary-button {
  font: inherit;
}

.icon-button {
  width: 36px;
  height: 36px;
  border: 1px solid var(--border-strong);
  border-radius: 12px;
  background: var(--surface-2);
  color: var(--text-secondary);
  cursor: pointer;
}

.new-chat-button {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  height: 38px;
  border: 1px solid var(--border-strong);
  border-radius: 10px;
  background: var(--surface-2);
  color: var(--text-primary);
  cursor: pointer;
}

.sidebar-section {
  display: grid;
  gap: 6px;
}

.sidebar-label {
  margin: 0;
  color: var(--text-tertiary);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.nav-pill,
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 8px 10px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  text-align: left;
}

.nav-pill:hover,
.section-header:hover,
.session-item:hover,
.icon-button:hover,
.account-button:hover,
.menu-action:hover,
.new-chat-button:hover {
  background: var(--surface-2);
  border-color: var(--border-strong);
  color: var(--text-primary);
}

.nav-pill.active {
  background: rgba(25, 195, 125, 0.12);
  border-color: rgba(25, 195, 125, 0.28);
  color: #baf3d0;
}

.sessions-panel {
  min-height: 0;
  flex: 1;
}

.session-list {
  display: grid;
  gap: 3px;
  min-height: 0;
  overflow: auto;
}

.sidebar-state {
  margin: 0;
  padding: 8px 10px;
  color: var(--text-tertiary);
  font-size: 12px;
}

.session-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  min-height: 34px;
  padding: 6px 8px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
  text-align: left;
}

.session-item.active {
  background: rgba(255, 255, 255, 0.05);
  border-color: var(--border-strong);
}

.session-title {
  flex: 1;
  min-width: 0;
  color: var(--text-primary);
  font-size: 12px;
  line-height: 1.2;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-meta {
  flex: 0 0 auto;
  color: var(--text-tertiary);
  font-size: 10px;
  opacity: 0.72;
}

.main-panel {
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 100vh;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 18px 28px 12px;
}

.account-area {
  position: relative;
}

.account-button {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px 8px 8px;
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-primary);
  cursor: pointer;
}

.account-avatar {
  display: inline-grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: linear-gradient(135deg, #2ad38b, #1a7f52);
  color: #04130b;
  font-size: 13px;
  font-weight: 700;
}

.account-name {
  font-size: 14px;
}

.account-menu {
  position: absolute;
  top: calc(100% + 10px);
  right: 0;
  min-width: 180px;
  padding: 10px;
  border: 1px solid var(--border-strong);
  border-radius: 16px;
  background: rgba(28, 31, 37, 0.97);
  box-shadow: 0 18px 50px rgba(0, 0, 0, 0.35);
}

.account-menu-user {
  display: block;
  padding: 10px 12px 8px;
  color: var(--text-secondary);
  font-size: 13px;
}

.menu-action {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid transparent;
  border-radius: 12px;
  background: transparent;
  color: var(--text-primary);
  cursor: pointer;
  text-align: left;
}

.conversation-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 12px 0 180px;
}

.conversation-scroll > * {
  width: min(880px, calc(100% - 32px));
  margin-inline: auto;
}

.empty-state {
  min-height: calc(100vh - 320px);
  display: grid;
  place-content: center;
  gap: 14px;
  text-align: center;
}

.empty-mark {
  width: 56px;
  height: 56px;
  margin: 0 auto;
  display: grid;
  place-items: center;
  border-radius: 18px;
  background: radial-gradient(circle at top, rgba(25, 195, 125, 0.3), rgba(25, 195, 125, 0.06));
  color: #c8f9dc;
  font-size: 24px;
}

.empty-state p {
  margin: 0;
  color: var(--text-secondary);
}

.message-row {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr);
  gap: 14px;
  padding: 18px 0;
}

.message-row.user {
  grid-template-columns: minmax(0, 1fr) 36px;
}

.message-row.user .message-avatar {
  order: 2;
}

.message-row.user .message-body {
  order: 1;
  align-items: flex-end;
}

.message-avatar {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: var(--surface-2);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 700;
}

.message-row.assistant .message-avatar {
  background: linear-gradient(135deg, #1f8f5f, #164d36);
  color: #dffff0;
}

.message-row.user .message-avatar {
  background: linear-gradient(135deg, #5f6b84, #394255);
  color: white;
}

.message-row.thinking .message-avatar {
  background: linear-gradient(135deg, #363a43, #272a31);
}

.message-body {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.message-card {
  min-width: 0;
  color: var(--text-primary);
}

.assistant-card {
  padding-right: 24px;
}

.user-card {
  max-width: min(720px, 100%);
  padding: 14px 16px;
  border: 1px solid var(--border-strong);
  border-radius: 22px;
  background: var(--surface-3);
}

.thinking-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border: 1px solid var(--border-soft);
  border-radius: 14px 14px 0 0;
  background: rgba(255, 255, 255, 0.03);
  color: var(--text-secondary);
  cursor: pointer;
  user-select: none;
}

.thinking-toggle {
  color: var(--text-tertiary);
  font-size: 13px;
}

.thinking-card {
  padding: 14px;
  border: 1px solid var(--border-soft);
  border-top: none;
  border-radius: 0 0 14px 14px;
  background: rgba(255, 255, 255, 0.025);
  color: var(--text-secondary);
}

.composer-wrap {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 24px 16px 30px;
  background: linear-gradient(180deg, rgba(13, 14, 18, 0) 0%, rgba(13, 14, 18, 0.92) 30%, rgba(13, 14, 18, 1) 100%);
}

.composer {
  width: min(880px, calc(100% - 8px));
  margin: 0 auto;
  padding: 14px;
  border: 1px solid var(--border-strong);
  border-radius: 26px;
  background: rgba(31, 34, 40, 0.96);
  box-shadow: 0 24px 90px rgba(0, 0, 0, 0.32);
  backdrop-filter: blur(18px);
}

.composer-input {
  width: 100%;
  min-height: 28px;
  max-height: 220px;
  padding: 4px 4px 10px;
  border: none;
  background: transparent;
  color: var(--text-primary);
  font: inherit;
  line-height: 1.6;
  resize: none;
  box-sizing: border-box;
}

.composer-input:focus {
  outline: none;
}

.composer-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.composer-hint {
  color: var(--text-tertiary);
  font-size: 12px;
}

.primary-button {
  height: 42px;
  padding: 0 16px;
  border: 1px solid transparent;
  border-radius: 14px;
  background: var(--accent);
  color: #03110a;
  font-weight: 600;
  cursor: pointer;
}

.primary-button:hover {
  filter: brightness(1.04);
}

.primary-button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.send-button.stop {
  background: #d06b6b;
  color: white;
}

.markdown-body {
  color: inherit !important;
  background: transparent !important;
  font-size: 15px;
  line-height: 1.75;
}

.markdown-body :deep(p) {
  margin: 0 0 14px;
}

.markdown-body :deep(p:last-child) {
  margin-bottom: 0;
}

.markdown-body :deep(pre) {
  margin: 16px 0;
  padding: 14px 16px;
  border: 1px solid var(--border-strong);
  border-radius: 16px;
  background: #111318 !important;
  overflow-x: auto;
}

.markdown-body :deep(code) {
  padding: 0.18em 0.45em;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.08) !important;
  color: #def7e8 !important;
}

.markdown-body :deep(pre code) {
  padding: 0;
  background: transparent !important;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  padding-left: 22px;
}

.markdown-body :deep(a) {
  color: #88d4ad;
}

@media (max-width: 980px) {
  .workspace {
    grid-template-columns: 1fr;
  }

  .sidebar {
    display: none;
  }

  .topbar {
    padding-inline: 16px;
  }

  .conversation-scroll {
    padding-bottom: 196px;
  }
}

@media (max-width: 640px) {
  .login-screen {
    padding: 18px;
  }

  .login-card {
    padding: 24px;
    border-radius: 22px;
  }

  .topbar {
    align-items: flex-start;
  }

  .account-name,
  .composer-hint {
    display: none;
  }

  .message-row,
  .message-row.user {
    grid-template-columns: 28px minmax(0, 1fr);
    gap: 10px;
  }

  .message-row.user .message-avatar {
    order: 0;
  }

  .message-row.user .message-body {
    order: 0;
    align-items: stretch;
  }
}
</style>
