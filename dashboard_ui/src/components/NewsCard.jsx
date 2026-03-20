export default function NewsCard({ article }) {
  const time = article.published_at
    ? new Date(article.published_at * 1000 || article.published_at).toLocaleDateString()
    : ''

  return (
    <a
      href={article.url || '#'}
      target="_blank"
      rel="noopener noreferrer"
      className="block bg-gray-800 rounded-lg p-3 border border-gray-700 hover:border-gray-500 transition-colors"
    >
      <p className="text-white text-sm font-medium leading-snug line-clamp-2">{article.title}</p>
      <div className="flex justify-between items-center mt-2">
        <span className="text-xs text-gray-500">{article.publisher}</span>
        {time && <span className="text-xs text-gray-600">{time}</span>}
      </div>
    </a>
  )
}
