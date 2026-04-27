<template>
  <div class="chat-container">
    <div class="chat-box">
      <div ref="messagesRef" class="messages">
        <div v-if="messages.length === 0" class="empty-state">
          <el-icon :size="60" color="#30363d"><ChatDotRound /></el-icon>
          <p>开始提问吧，我会基于知识库内容回答，并显示引用来源。</p>
        </div>

        <div
          v-for="(msg, index) in messages"
          :key="index"
          class="message-item"
          :class="msg.role"
        >
          <div class="avatar">
            <el-avatar :icon="msg.role === 'user' ? User : Service" :style="{ backgroundColor: msg.role === 'user' ? '#409EFF' : '#00c36f' }" />
          </div>
          <div class="content">
            <div class="bubble">
              <div v-if="msg.loading" class="typing-indicator">
                <span></span><span></span><span></span>
              </div>
              <template v-else>
                <div v-html="formatContent(msg.content)"></div>
                <div v-if="msg.sources?.length" class="sources">
                  <div class="sources-title">引用来源</div>
                  <div
                    v-for="source in msg.sources"
                    :key="source.chunk_id"
                    class="source-item"
                  >
                    <div class="source-header">
                      <span>{{ source.title }}</span>
                      <span class="score">{{ formatScore(source.score) }}</span>
                    </div>
                    <div class="source-snippet">{{ source.snippet }}</div>
                  </div>
                </div>
              </template>
            </div>
          </div>
        </div>
      </div>

      <div class="input-area">
        <el-input
          v-model="input"
          placeholder="请输入您的问题..."
          :rows="3"
          type="textarea"
          resize="none"
          @keydown.enter.prevent="handleSend"
        />
        <el-button type="primary" class="send-btn" @click="handleSend" :loading="loading" :disabled="!input.trim()">
          <el-icon><Position /></el-icon> 发送
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { nextTick, ref } from 'vue'
import { ChatDotRound, Position, Service, User } from '@element-plus/icons-vue'
import { marked } from 'marked'
import { queryKnowledge } from '@/api/knowledge'

const input = ref('')
const loading = ref(false)
const messages = ref([])
const messagesRef = ref(null)

const scrollToBottom = () => {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

const formatContent = (text) => marked(text || '')

const formatScore = (score) => {
  if (typeof score !== 'number') return ''
  return `匹配度 ${score.toFixed(3)}`
}

const handleSend = async () => {
  if (!input.value.trim() || loading.value) return

  const question = input.value
  input.value = ''

  messages.value.push({
    role: 'user',
    content: question
  })
  scrollToBottom()

  loading.value = true
  messages.value.push({
    role: 'assistant',
    content: '',
    sources: [],
    loading: true
  })
  scrollToBottom()

  try {
    const res = await queryKnowledge({ question })
    const botMsg = messages.value[messages.value.length - 1]
    botMsg.loading = false
    botMsg.content = res.answer
    botMsg.sources = res.sources || []
  } catch (error) {
    const botMsg = messages.value[messages.value.length - 1]
    botMsg.loading = false
    botMsg.content = '抱歉，知识库查询失败，请稍后重试。'
    botMsg.sources = []
  } finally {
    loading.value = false
    scrollToBottom()
  }
}
</script>

<style lang="scss" scoped>
.chat-container {
  height: calc(100vh - 40px);
  display: flex;
  flex-direction: column;
}

.chat-box {
  flex: 1;
  background-color: #161b22;
  border: 1px solid #30363d;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.messages {
  flex: 1;
  padding: 20px;
  overflow-y: auto;

  .empty-state {
    height: 100%;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    color: #8b949e;

    p {
      margin-top: 20px;
    }
  }
}

.message-item {
  display: flex;
  margin-bottom: 20px;

  &.user {
    flex-direction: row-reverse;

    .content {
      align-items: flex-end;

      .bubble {
        background-color: #409eff;
        color: #fff;
        border-top-right-radius: 0;
      }
    }

    .avatar {
      margin-left: 10px;
      margin-right: 0;
    }
  }

  &.assistant {
    .content {
      align-items: flex-start;

      .bubble {
        background-color: #1f242d;
        color: #c9d1d9;
        border: 1px solid #30363d;
        border-top-left-radius: 0;
      }
    }

    .avatar {
      margin-right: 10px;
    }
  }
}

.content {
  display: flex;
  flex-direction: column;
  max-width: 72%;

  .bubble {
    padding: 10px 15px;
    border-radius: 12px;
    line-height: 1.5;
    font-size: 14px;
    word-break: break-word;

    :deep(p) {
      margin: 0 0 10px 0;

      &:last-child {
        margin-bottom: 0;
      }
    }

    :deep(a) {
      color: #58a6ff;
      text-decoration: none;

      &:hover {
        text-decoration: underline;
      }
    }

    :deep(ul),
    :deep(ol) {
      padding-left: 20px;
      margin: 5px 0;
    }

    :deep(code) {
      background-color: rgba(110, 118, 129, 0.4);
      padding: 0.2em 0.4em;
      border-radius: 6px;
      font-family: monospace;
    }

    :deep(pre) {
      background-color: #161b22;
      padding: 10px;
      border-radius: 6px;
      overflow-x: auto;

      code {
        background-color: transparent;
        padding: 0;
      }
    }
  }
}

.sources {
  margin-top: 14px;
  border-top: 1px solid #30363d;
  padding-top: 12px;

  .sources-title {
    font-size: 12px;
    color: #8b949e;
    margin-bottom: 10px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }

  .source-item {
    background-color: #11161d;
    border: 1px solid #2a3240;
    border-radius: 8px;
    padding: 10px 12px;
    margin-bottom: 10px;
  }

  .source-header {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    color: #e6edf3;
    font-weight: 600;
    margin-bottom: 6px;
  }

  .score {
    color: #58a6ff;
    white-space: nowrap;
    font-weight: 500;
  }

  .source-snippet {
    color: #9da7b3;
    font-size: 13px;
    white-space: pre-wrap;
  }
}

.input-area {
  padding: 20px;
  background-color: #0d1117;
  border-top: 1px solid #30363d;
  display: flex;
  gap: 10px;
  align-items: flex-end;

  :deep(.el-textarea__inner) {
    background-color: #161b22;
    border-color: #30363d;
    color: #c9d1d9;
    box-shadow: none;

    &:focus {
      border-color: #409eff;
    }
  }

  .send-btn {
    height: auto;
    padding: 10px 20px;
  }
}

.typing-indicator {
  span {
    display: inline-block;
    width: 6px;
    height: 6px;
    background-color: #8b949e;
    border-radius: 50%;
    margin: 0 2px;
    animation: bounce 1.4s infinite ease-in-out both;

    &:nth-child(1) {
      animation-delay: -0.32s;
    }

    &:nth-child(2) {
      animation-delay: -0.16s;
    }
  }
}

@keyframes bounce {
  0%,
  80%,
  100% {
    transform: scale(0);
  }

  40% {
    transform: scale(1);
  }
}
</style>
