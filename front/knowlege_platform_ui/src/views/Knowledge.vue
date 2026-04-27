<template>
  <div class="knowledge-container">
    <div class="page-header">
      <h2>知识库管理</h2>
      <p class="subtitle">上传文档后会在后台异步建立索引，可在下方查看处理状态。</p>
    </div>

    <el-card class="upload-card">
      <template #header>
        <div class="card-header">
          <span>文档上传</span>
        </div>
      </template>
      <div class="upload-area">
        <el-upload
          class="upload-demo"
          drag
          action=""
          :http-request="handleUpload"
          multiple
          :show-file-list="false"
        >
          <el-icon class="el-icon--upload"><upload-filled /></el-icon>
          <div class="el-upload__text">
            将文档拖到此处，或 <em>点击上传</em>
          </div>
          <template #tip>
            <div class="el-upload__tip">
              当前支持 Markdown / 文本类文档，上传后会自动切块并建立向量索引。
            </div>
          </template>
        </el-upload>
      </div>
    </el-card>

    <div v-if="uploadHistory.length > 0" class="history-section">
      <h3>索引任务</h3>
      <el-table :data="uploadHistory" style="width: 100%">
        <el-table-column prop="fileName" label="文件名" min-width="220" />
        <el-table-column prop="documentId" label="文档 ID" width="100" align="center" />
        <el-table-column prop="jobId" label="任务 ID" width="100" align="center" />
        <el-table-column prop="status" label="状态" width="120" align="center">
          <template #default="scope">
            <el-tag :type="statusTagType(scope.row.status)">
              {{ scope.row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="chunks" label="切片数" width="100" align="center" />
        <el-table-column prop="message" label="信息" min-width="260" />
        <el-table-column prop="time" label="更新时间" width="180" />
      </el-table>
    </div>

    <div v-if="documents.length > 0" class="history-section">
      <h3>知识库文档</h3>
      <el-table :data="documents" style="width: 100%">
        <el-table-column prop="id" label="ID" width="80" align="center" />
        <el-table-column prop="title" label="标题" min-width="260" />
        <el-table-column prop="status" label="状态" width="120" align="center">
          <template #default="scope">
            <el-tag :type="statusTagType(scope.row.status)">
              {{ scope.row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="chunks_count" label="切片数" width="100" align="center" />
        <el-table-column prop="updated_at" label="更新时间" width="180" />
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { UploadFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getDocuments, getIndexJob, uploadFile } from '@/api/knowledge'

const uploadHistory = ref([])
const documents = ref([])
const pollingJobs = ref(new Set())
let pollingTimer = null

const statusTagType = (status) => {
  if (status === 'success' || status === 'ready') return 'success'
  if (status === 'queued' || status === 'running' || status === 'indexing' || status === 'accepted') return 'warning'
  return 'danger'
}

const refreshDocuments = async () => {
  try {
    documents.value = await getDocuments()
  } catch (error) {
    console.error('load documents failed', error)
  }
}

const pollJobs = async () => {
  const jobIds = Array.from(pollingJobs.value)
  if (!jobIds.length) return

  await Promise.all(jobIds.map(async (jobId) => {
    try {
      const job = await getIndexJob(jobId)
      const historyItem = uploadHistory.value.find((item) => item.jobId === jobId)
      if (!historyItem) return

      historyItem.status = job.status
      historyItem.message = job.error_message || `文档当前状态：${job.document_status}`
      historyItem.time = new Date().toLocaleString()

      if (job.status === 'success' || job.status === 'failed') {
        pollingJobs.value.delete(jobId)
        await refreshDocuments()
      }
    } catch (error) {
      console.error('poll job failed', error)
      pollingJobs.value.delete(jobId)
    }
  }))

  if (!pollingJobs.value.size && pollingTimer) {
    clearInterval(pollingTimer)
    pollingTimer = null
  }
}

const ensurePolling = () => {
  if (!pollingTimer) {
    pollingTimer = setInterval(pollJobs, 2500)
  }
}

const handleUpload = async (options) => {
  const { file } = options
  const formData = new FormData()
  formData.append('file', file)

  try {
    const res = await uploadFile(formData)
    uploadHistory.value.unshift({
      fileName: res.file_name,
      documentId: res.document_id,
      jobId: res.job_id,
      chunks: res.chunks_added,
      status: res.job_status || res.status,
      message: res.message,
      time: new Date().toLocaleString()
    })

    pollingJobs.value.add(res.job_id)
    ensurePolling()
    await refreshDocuments()
    ElMessage.success(`文件 ${file.name} 已上传，后台开始建立索引`)
  } catch (error) {
    uploadHistory.value.unshift({
      fileName: file.name,
      documentId: '-',
      jobId: '-',
      chunks: 0,
      status: 'failed',
      message: error.message || '上传失败',
      time: new Date().toLocaleString()
    })
    ElMessage.error(`文件 ${file.name} 上传失败`)
  }
}

onMounted(async () => {
  await refreshDocuments()
})

onBeforeUnmount(() => {
  if (pollingTimer) {
    clearInterval(pollingTimer)
    pollingTimer = null
  }
})
</script>

<style lang="scss" scoped>
.knowledge-container {
  max-width: 1100px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 30px;

  h2 {
    color: #fff;
    margin-bottom: 10px;
  }

  .subtitle {
    color: #8b949e;
    font-size: 14px;
  }
}

.upload-card {
  background-color: #161b22;
  border: 1px solid #30363d;
  color: #c9d1d9;
  margin-bottom: 30px;

  :deep(.el-card__header) {
    border-bottom: 1px solid #30363d;
  }
}

.upload-area {
  padding: 20px;

  :deep(.el-upload-dragger) {
    background-color: #0d1117;
    border-color: #30363d;

    &:hover {
      border-color: #409eff;
      background-color: #161b22;
    }

    .el-icon--upload {
      color: #58a6ff;
    }

    .el-upload__text {
      color: #8b949e;

      em {
        color: #58a6ff;
      }
    }
  }
}

.history-section {
  margin-top: 24px;

  h3 {
    color: #fff;
    margin-bottom: 16px;
  }

  :deep(.el-table) {
    background-color: #161b22;
    color: #c9d1d9;
    --el-table-border-color: #30363d;
    --el-table-header-bg-color: #0d1117;
    --el-table-row-hover-bg-color: #1f242d;

    th,
    tr {
      background-color: #161b22;
    }
  }
}
</style>
