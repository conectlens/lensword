import '@testing-library/jest-dom'

// jsdom does not implement scrollIntoView. Stubbed here rather than guarded in
// the components: keeping a chat scrolled to the newest message is real
// behaviour, and a component that checked for the method's existence would be
// carrying test-environment knowledge in product code.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {}
}
