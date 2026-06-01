export const COURSE_CHAPTERS: Record<string, string> = {
  ch02: "Chương 2: NumPy, Pandas",
  ch03: "Chương 3: Pipeline và EDA",
  ch04: "Chương 4: Tiền xử lý dữ liệu",
  ch05: "Chương 5: Đánh giá mô hình",
  ch06: "Chương 6: Học không giám sát",
  ch07a: "Chương 7a: Hồi quy",
  ch07b: "Chương 7b: Phân loại",
  ch08: "Chương 8: Deep Learning và CNN",
  ch09: "Chương 9: Tinh chỉnh tham số",
  ch10: "Chương 10: Ensemble Models",
  ch11: "Chương 11: Triển khai mô hình",
}

export const TOPIC_SUGGESTIONS: Record<string, string[]> = {
  ch02: ["NumPy array operations", "Pandas DataFrame"],
  ch03: ["Data pipeline workflow", "Exploratory Data Analysis", "Data visualization"],
  ch04: ["SimpleImputer và KNNImputer trong sklearn", "dropna và fillna trong Pandas", "IQR method và Z-score để phát hiện outlier", "Isolation Forest outlier detection"],
  ch05: ["Classification Metrics", "Cross-validation"],
  ch06: ["K-Means Clustering", "PCA"],
  ch07a: ["Linear Regression", "Regularization"],
  ch07b: ["Decision Trees", "Logistic Regression", "SVM"],
  ch08: ["CNN Neural Networks", "Convolution Layer", "Pooling Layer"],
  ch09: ["Grid Search", "Random Search"],
  ch10: ["Random Forest", "Boosting", "Bagging"],
  ch11: ["Model Serving", "API Deployment"],
}

export const DIFFICULTY_LABELS: Record<string, string> = {
  G1: "G1 - Nhớ/Biết",
  G2: "G2 - Hiểu/Áp dụng",
  G3: "G3 - Phân tích",
}

export function chapterLabel(chapterId?: string | null): string {
  return COURSE_CHAPTERS[chapterId || ""] || "Chưa chọn chương"
}
