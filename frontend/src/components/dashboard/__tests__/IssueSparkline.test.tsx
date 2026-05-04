import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import IssueSparkline from '../IssueSparkline'

describe('<IssueSparkline />', () => {
  it('renders nothing for undefined data', () => {
    const { container } = render(<IssueSparkline data={undefined} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing for an empty array', () => {
    const { container } = render(<IssueSparkline data={[]} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders an SVG with a path and an endpoint dot for non-empty data', () => {
    render(<IssueSparkline data={[1, 2, 3, 4]} />)
    const svg = screen.getByTestId('issue-sparkline')
    expect(svg.tagName.toLowerCase()).toBe('svg')
    // Two paths (area + line) + one circle (endpoint dot)
    expect(svg.querySelectorAll('path').length).toBe(2)
    expect(svg.querySelectorAll('circle').length).toBe(1)
  })

  it('respects a custom width and height', () => {
    render(<IssueSparkline data={[1, 2, 3]} width={200} height={50} />)
    const svg = screen.getByTestId('issue-sparkline')
    expect(svg.getAttribute('width')).toBe('200')
    expect(svg.getAttribute('height')).toBe('50')
  })
})
