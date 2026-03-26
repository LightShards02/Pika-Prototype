import { useStore } from '../store';
import { PlainTextViewer } from './PlainTextViewer';
import { TableViewer } from './TableViewer';

export const AppendixViewer = ({ appendixId }: { appendixId: string }) => {
  const appendix = useStore((state) => state.appendixes.find((a) => a.id === appendixId));

  if (!appendix) return null;

  return appendix.type === 'table'
    ? <TableViewer appendix={appendix} />
    : <PlainTextViewer appendix={appendix} />;
};
