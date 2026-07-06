{{/* Generate base name */}}
{{- define "anomaly-scoring-api.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "anomaly-scoring-api.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "anomaly-scoring-api.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "anomaly-scoring-api.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "anomaly-scoring-api.labels" -}}
app.kubernetes.io/name: {{ include "anomaly-scoring-api.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "anomaly-scoring-api.selectorLabels" -}}
app.kubernetes.io/name: {{ include "anomaly-scoring-api.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
