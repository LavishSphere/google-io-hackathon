import { forwardRef } from 'react';

type Props = { src: string };

const VideoPlayer = forwardRef<HTMLVideoElement, Props>(({ src }, ref) => {
  return (
    <video
      ref={ref}
      src={src}
      controls
      crossOrigin="anonymous"
      playsInline
    />
  );
});

VideoPlayer.displayName = 'VideoPlayer';
export default VideoPlayer;
